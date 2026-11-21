#!/usr/bin/env python3
"""Replace a proven native Android lifecycle wrapper with an invoke-super bridge in Smali."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


LIFECYCLE_METHODS = {
    "attachBaseContext",
    "onActivityResult",
    "onConfigurationChanged",
    "onCreate",
    "onDestroy",
    "onLowMemory",
    "onNewIntent",
    "onPause",
    "onRestart",
    "onResume",
    "onStart",
    "onStop",
    "onTrimMemory",
}


def descriptor(name: str) -> str:
    if name.startswith("L") and name.endswith(";"):
        return name
    return "L" + name.replace(".", "/") + ";"


def find_smali(smali_root: Path, class_name: str) -> Path:
    relative = Path(*class_name.split("."))
    relative = relative.with_suffix(".smali")
    candidates = [smali_root / relative]
    candidates.extend(sorted(root / relative for root in smali_root.glob("smali*") if root.is_dir()))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"could not find {class_name} below {smali_root}")


def parameter_register_count(proto: str) -> int:
    if not proto.startswith("(") or ")" not in proto:
        raise ValueError("invalid method prototype")
    params = proto[1:proto.index(")")]
    count = 0
    index = 0
    while index < len(params):
        token = params[index]
        if token == "[":
            while index < len(params) and params[index] == "[":
                index += 1
            if index >= len(params):
                raise ValueError("invalid array type in prototype")
            if params[index] == "L":
                end = params.find(";", index)
                if end < 0:
                    raise ValueError("unterminated object type in prototype")
                index = end + 1
            else:
                index += 1
            count += 1
        elif token == "L":
            end = params.find(";", index)
            if end < 0:
                raise ValueError("unterminated object type in prototype")
            index = end + 1
            count += 1
        elif token in "ZBSCIF":
            index += 1
            count += 1
        elif token in "JD":
            index += 1
            count += 2
        else:
            raise ValueError(f"invalid type in prototype: {token}")
    return count


def has_concrete_method(text: str, method: str, proto: str) -> bool:
    signature = re.escape(method + proto)
    for match in re.finditer(rf"(?m)^\.method(?:\s+(?P<modifiers>.*?))?\s+{signature}\s*$", text):
        modifiers = set((match.group("modifiers") or "").split())
        if "native" not in modifiers and "abstract" not in modifiers:
            return True
    return False


def replace_method(text: str, wrapper: str, core: str, method: str, proto: str) -> str:
    signature = method + proto
    start_pattern = re.compile(rf"(?m)^\.method(?:\s+(?P<modifiers>.*?))?\s+{re.escape(signature)}\s*$")
    match = start_pattern.search(text)
    if not match:
        raise ValueError(f"wrapper has no method {signature}")
    end_match = re.search(r"(?m)^\.end method\s*$", text[match.end():])
    if not end_match:
        raise ValueError(f"wrapper method {signature} has no .end method")
    end = match.end() + end_match.end()
    modifiers = (match.group("modifiers") or "").split()
    if "native" not in modifiers:
        raise ValueError(f"wrapper method {signature} is not native")
    if "static" in modifiers:
        raise ValueError("static native methods are not lifecycle wrappers")
    modifiers = [modifier for modifier in modifiers if modifier not in {"native", "abstract"}]
    p_last = parameter_register_count(proto)
    declaration = ".method" + (" " + " ".join(modifiers) if modifiers else "") + f" {signature}"
    core_descriptor = descriptor(core)
    replacement = "\n".join(
        (
            declaration,
            "    .locals 0",
            "",
            f"    invoke-super/range {{p0 .. p{p_last}}}, {core_descriptor}->{signature}",
            "",
            "    return-void",
            ".end method",
        )
    )
    return text[:match.start()] + replacement + text[end:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smali-root", type=Path, required=True, help="apktool output root or a smali directory")
    parser.add_argument("--wrapper", required=True, help="Native wrapper class, for example com.example.MainActivity")
    parser.add_argument("--core", required=True, help="Concrete direct superclass, for example com.example.MainActivityCore")
    parser.add_argument("--method", required=True, choices=sorted(LIFECYCLE_METHODS))
    parser.add_argument("--proto", required=True, help="Void lifecycle method prototype")
    parser.add_argument("--out", type=Path, required=True, help="Patched wrapper .smali output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.proto.endswith("V"):
        raise SystemExit("only void Android lifecycle methods can be bridged")
    wrapper_path = find_smali(args.smali_root, args.wrapper)
    core_path = find_smali(args.smali_root, args.core)
    wrapper_text = wrapper_path.read_text(encoding="utf-8")
    core_text = core_path.read_text(encoding="utf-8")
    wrapper_descriptor = descriptor(args.wrapper)
    core_descriptor = descriptor(args.core)
    if not re.search(rf"(?m)^\.class(?:\s+.*)?\s+{re.escape(wrapper_descriptor)}\s*$", wrapper_text):
        raise SystemExit("wrapper class declaration does not match --wrapper")
    if not re.search(rf"(?m)^\.super\s+{re.escape(core_descriptor)}\s*$", wrapper_text):
        raise SystemExit("--core is not the wrapper's direct superclass")
    if not has_concrete_method(core_text, args.method, args.proto):
        raise SystemExit("core class has no matching concrete lifecycle method")
    patched = replace_method(wrapper_text, args.wrapper, args.core, args.method, args.proto)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(patched, encoding="utf-8", newline="\n")
    print(args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
