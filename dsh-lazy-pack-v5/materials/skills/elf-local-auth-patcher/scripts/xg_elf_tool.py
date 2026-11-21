#!/usr/bin/env python3
"""
西宫公益频道@xigongPD - ELF/APK local-test reverse helper.

Stdlib-only toolkit for:
  - ELF header/program-header parsing
  - VA -> file offset mapping
  - expected-bytes guarded in-place patching
  - APK zip inventory and exact entry replacement
  - overlay/driver/proc-mem signal scanning
  - Android adb evidence collection
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any


PT_LOAD = 1


def parse_int(value: str | int) -> int:
    if isinstance(value, int):
        return value
    value = value.strip()
    return int(value, 16) if value.lower().startswith("0x") else int(value, 10)


def parse_hex_bytes(value: str) -> bytes:
    clean = value.replace(" ", "").replace("_", "").replace(":", "")
    if len(clean) % 2:
        raise ValueError(f"hex string has odd length: {value!r}")
    return bytes.fromhex(clean)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unpack(fmt: str, data: bytes, offset: int):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, data[offset : offset + size])


def parse_elf(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    data = p.read_bytes()
    if len(data) < 0x40 or data[:4] != b"\x7fELF":
        raise ValueError(f"not an ELF file: {p}")

    elf_class = data[4]
    endian_id = data[5]
    if elf_class not in (1, 2):
        raise ValueError(f"unsupported ELF class: {elf_class}")
    if endian_id not in (1, 2):
        raise ValueError(f"unsupported ELF endian: {endian_id}")
    endian = "<" if endian_id == 1 else ">"

    if elf_class == 2:
        header_fmt = endian + "HHIQQQIHHHHHH"
        keys = [
            "e_type",
            "e_machine",
            "e_version",
            "e_entry",
            "e_phoff",
            "e_shoff",
            "e_flags",
            "e_ehsize",
            "e_phentsize",
            "e_phnum",
            "e_shentsize",
            "e_shnum",
            "e_shstrndx",
        ]
        values = _unpack(header_fmt, data, 0x10)
        ph_fmt = endian + "IIQQQQQQ"
        ph_keys = ["p_type", "p_flags", "p_offset", "p_vaddr", "p_paddr", "p_filesz", "p_memsz", "p_align"]
    else:
        header_fmt = endian + "HHIIIIIHHHHHH"
        keys = [
            "e_type",
            "e_machine",
            "e_version",
            "e_entry",
            "e_phoff",
            "e_shoff",
            "e_flags",
            "e_ehsize",
            "e_phentsize",
            "e_phnum",
            "e_shentsize",
            "e_shnum",
            "e_shstrndx",
        ]
        values = _unpack(header_fmt, data, 0x10)
        ph_fmt = endian + "IIIIIIII"
        ph_keys = ["p_type", "p_offset", "p_vaddr", "p_paddr", "p_filesz", "p_memsz", "p_flags", "p_align"]

    header = dict(zip(keys, values))
    segments = []
    ph_size = struct.calcsize(ph_fmt)
    if header["e_phentsize"] < ph_size:
        raise ValueError("program header entry size is smaller than expected")
    for i in range(header["e_phnum"]):
        off = header["e_phoff"] + i * header["e_phentsize"]
        if off + ph_size > len(data):
            raise ValueError("program header table exceeds file size")
        seg = dict(zip(ph_keys, _unpack(ph_fmt, data, off)))
        seg["index"] = i
        seg["file_header_offset"] = off
        segments.append(seg)

    return {
        "path": str(p.resolve()),
        "size": len(data),
        "sha256": sha256_file(p),
        "class": 64 if elf_class == 2 else 32,
        "endian": "little" if endian == "<" else "big",
        "header": header,
        "segments": segments,
    }


def va_to_offset(segments: list[dict[str, Any]], va: int) -> int:
    for seg in segments:
        if seg.get("p_type") != PT_LOAD:
            continue
        start = int(seg["p_vaddr"])
        end = start + int(seg["p_filesz"])
        if start <= va < end:
            return int(seg["p_offset"]) + (va - start)
    raise ValueError(f"VA 0x{va:x} is not inside any PT_LOAD file range")


def _header_slices(elf: dict[str, Any]) -> tuple[slice, slice]:
    h = elf["header"]
    eh = slice(0, int(h["e_ehsize"]))
    ph = slice(int(h["e_phoff"]), int(h["e_phoff"]) + int(h["e_phentsize"]) * int(h["e_phnum"]))
    return eh, ph


def patch_bytes(
    input_path: str | Path,
    output_path: str | Path,
    va: int,
    expected: bytes,
    patch: bytes,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    if len(expected) != len(patch):
        raise ValueError("expected and patch bytes must have identical length")

    src = Path(input_path)
    out = Path(output_path)
    original = src.read_bytes()
    elf = parse_elf(src)
    off = va_to_offset(elf["segments"], va)
    actual = original[off : off + len(expected)]
    if actual != expected:
        raise ValueError(
            f"expected bytes mismatch at VA 0x{va:x}/file 0x{off:x}: "
            f"expected {expected.hex()}, actual {actual.hex()}"
        )

    patched = bytearray(original)
    patched[off : off + len(patch)] = patch
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(patched)

    patched_elf = parse_elf(out)
    eh, ph = _header_slices(elf)
    report = {
        "tool": "xg_elf_tool.py",
        "author": "西宫公益频道@xigongPD",
        "input": str(src.resolve()),
        "output": str(out.resolve()),
        "va": f"0x{va:x}",
        "file_offset": f"0x{off:x}",
        "old_bytes": expected.hex(),
        "new_bytes": patch.hex(),
        "input_sha256": elf["sha256"],
        "output_sha256": patched_elf["sha256"],
        "verify": {
            "expected_bytes_matched": True,
            "same_size": len(original) == len(patched),
            "entry_unchanged": elf["header"]["e_entry"] == patched_elf["header"]["e_entry"],
            "elf_header_unchanged": original[eh] == bytes(patched)[eh],
            "program_headers_unchanged": original[ph] == bytes(patched)[ph],
            "patch_bytes_match": bytes(patched)[off : off + len(patch)] == patch,
        },
    }
    if report_path:
        rp = Path(report_path)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def apk_inventory(apk_path: str | Path) -> dict[str, Any]:
    apk = Path(apk_path)
    with zipfile.ZipFile(apk) as z:
        entries = []
        for info in z.infolist():
            entries.append(
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "crc": f"0x{info.CRC:08x}",
                }
            )
    return {
        "apk": str(apk.resolve()),
        "sha256": sha256_file(apk),
        "entries": entries,
        "assets_bin": [e["name"] for e in entries if e["name"].startswith("assets/bin/")],
        "libs": [e["name"] for e in entries if e["name"].startswith("lib/")],
        "has_meta_inf": any(e["name"].startswith("META-INF/") for e in entries),
    }


def apk_replace_entry(apk_path: str | Path, entry: str, replacement: str | Path, output_path: str | Path) -> dict[str, Any]:
    apk = Path(apk_path)
    repl = Path(replacement)
    out = Path(output_path)
    found = False
    removed_meta = False
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk, "r") as zin, zipfile.ZipFile(out, "w") as zout:
        for item in zin.infolist():
            name = item.filename
            if name.startswith("META-INF/"):
                removed_meta = True
                continue
            if name == entry:
                found = True
                continue
            zout.writestr(item, zin.read(name))
        if not found:
            raise ValueError(f"entry not found in APK: {entry}")
        zout.writestr(entry, repl.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    return {
        "input_apk": str(apk.resolve()),
        "output_apk": str(out.resolve()),
        "entry": entry,
        "replacement": str(repl.resolve()),
        "removed_meta_inf": removed_meta,
        "output_sha256": sha256_file(out),
    }


SIGNAL_KEYWORDS = {
    "java_status_overlay": ["SYSTEM_ALERT_WINDOW", "WindowManager", "TextView", "addView"],
    "game_overlay_or_menu": ["Canvas", "SurfaceView", "GLSurfaceView", "OpenGL", "setOnTouchListener", "Overlay Service"],
    "proc_mem_injection": ["/proc/%d/mem", "/proc/", "/mem", "pwrite", "process_vm_writev", "libUE4.so", "maps", "pidof"],
    "driver_chain": ["insmod", "modprobe", ".ko", "/dev/", "ioctl", "Magisk", "KernelSU", "sysfs"],
    "loader_chain": ["memfd_create", "fexecve", "execveat", "/proc/self/fd", "stdin", "chmod", "codeCacheDir"],
    "auth_chain": ["kami", "card", "license", "vip", "expire", "验证失败", "卡密不存在", "授权成功"],
}


def classify_text(text: str) -> dict[str, Any]:
    lower = text.lower()
    hits: dict[str, list[str]] = {}
    for name, words in SIGNAL_KEYWORDS.items():
        matched = []
        for w in words:
            if w.lower() in lower:
                matched.append(w)
        if matched:
            hits[name] = matched
    signals = sorted(hits)
    verdicts = []
    if "java_status_overlay" in hits and "game_overlay_or_menu" not in hits:
        verdicts.append("状态提示悬浮窗迹象强；未见游戏内功能菜单证据")
    if "proc_mem_injection" in hits and "driver_chain" not in hits:
        verdicts.append("纯 /proc/<pid>/mem 内存写入迹象强；未见 driver 刷入证据")
    if "driver_chain" in hits:
        verdicts.append("存在 driver 链关键词，需要继续查 .ko/insmod/ioctl/dev 节点")
    return {"signals": signals, "hits": hits, "verdicts": verdicts}


def scan_text_path(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if p.is_dir():
        parts = []
        for f in p.rglob("*"):
            if f.is_file() and f.stat().st_size <= 5 * 1024 * 1024:
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        text = "\n".join(parts)
    elif zipfile.is_zipfile(p):
        parts = []
        with zipfile.ZipFile(p) as z:
            for name in z.namelist():
                if name.endswith((".xml", ".html", ".txt", ".json", ".js", ".smali")) or name.startswith("assets/"):
                    try:
                        parts.append(z.read(name).decode("utf-8", errors="ignore"))
                    except Exception:
                        pass
        text = "\n".join(parts)
    else:
        text = p.read_text(encoding="utf-8", errors="ignore")
    result = classify_text(text)
    result["path"] = str(p.resolve())
    return result


def _run(cmd: list[str], timeout: int = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def device_probe(app_pkg: str, target_pkg: str, out_dir: str | Path) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    evidence: dict[str, Any] = {
        "timestamp": stamp,
        "app_pkg": app_pkg,
        "target_pkg": target_pkg,
        "commands": {},
        "files": {},
    }
    commands = {
        "devices": ["adb", "devices", "-l"],
        "model": ["adb", "shell", "getprop", "ro.product.model"],
        "android": ["adb", "shell", "getprop", "ro.build.version.release"],
        "abi": ["adb", "shell", "getprop", "ro.product.cpu.abi"],
        "root_id": ["adb", "shell", "su", "-c", "id"],
        "app_path": ["adb", "shell", "pm", "path", app_pkg],
        "overlay_appops": ["adb", "shell", "appops", "get", app_pkg, "SYSTEM_ALERT_WINDOW"],
        "focus": ["adb", "shell", "dumpsys", "window"],
        "target_pid": ["adb", "shell", "su", "-c", f"pidof {target_pkg}"],
        "target_ps": ["adb", "shell", "su", "-c", f"ps -A | grep {target_pkg}"],
    }
    for name, cmd in commands.items():
        evidence["commands"][name] = _run(cmd, timeout=30)

    pid = evidence["commands"].get("target_pid", "").split()
    if pid:
        p = pid[0]
        evidence["commands"]["target_cmdline"] = _run(["adb", "shell", "su", "-c", f"cat /proc/{p}/cmdline | tr '\\0' ' '"], 20)
        evidence["commands"]["target_maps_ue4"] = _run(["adb", "shell", "su", "-c", f"grep libUE4.so /proc/{p}/maps | head -n 10"], 20)
        evidence["commands"]["target_mem_perm"] = _run(["adb", "shell", "su", "-c", f"ls -l /proc/{p}/mem"], 20)

    log_path = out / f"logcat_{stamp}.txt"
    log_path.write_text(_run(["adb", "logcat", "-d", "-v", "time"], timeout=60), encoding="utf-8")
    evidence["files"]["logcat"] = str(log_path.resolve())

    screen_path = out / f"screen_{stamp}.png"
    adb = shutil.which("adb")
    if adb:
        with screen_path.open("wb") as f:
            try:
                subprocess.run([adb, "exec-out", "screencap", "-p"], stdout=f, stderr=subprocess.DEVNULL, timeout=20)
                evidence["files"]["screencap"] = str(screen_path.resolve())
            except Exception as e:
                evidence["files"]["screencap_error"] = repr(e)

    report_path = out / f"device_probe_{stamp}.json"
    report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["report"] = str(report_path.resolve())
    return evidence


def write_json(obj: Any, out: str | Path | None):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    print(text)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ELF/APK local-test reverse helper by 西宫公益频道@xigongPD")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("elf-info", help="parse ELF headers and PT_LOAD segments")
    s.add_argument("elf")
    s.add_argument("--json-out")

    s = sub.add_parser("va2off", help="map ELF virtual address to file offset")
    s.add_argument("elf")
    s.add_argument("va")

    s = sub.add_parser("patch-bytes", help="expected-bytes guarded in-place ELF patch")
    s.add_argument("--input", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--va", required=True)
    s.add_argument("--expected-hex", required=True)
    s.add_argument("--patch-hex", required=True)
    s.add_argument("--report")

    s = sub.add_parser("apk-inventory", help="list APK zip entries and key buckets")
    s.add_argument("apk")
    s.add_argument("--json-out")

    s = sub.add_parser("apk-replace-entry", help="replace one APK zip entry and remove META-INF signatures")
    s.add_argument("--apk", required=True)
    s.add_argument("--entry", required=True)
    s.add_argument("--replacement", required=True)
    s.add_argument("--out", required=True)

    s = sub.add_parser("scan-text", help="classify overlay/driver/mem-injection/loader/auth signals")
    s.add_argument("path")
    s.add_argument("--json-out")

    s = sub.add_parser("device-probe", help="collect adb evidence for real-device validation")
    s.add_argument("--app", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--out-dir", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.cmd == "elf-info":
        write_json(parse_elf(args.elf), args.json_out)
    elif args.cmd == "va2off":
        elf = parse_elf(args.elf)
        off = va_to_offset(elf["segments"], parse_int(args.va))
        print(f"0x{off:x}")
    elif args.cmd == "patch-bytes":
        report = patch_bytes(
            args.input,
            args.output,
            parse_int(args.va),
            parse_hex_bytes(args.expected_hex),
            parse_hex_bytes(args.patch_hex),
            args.report,
        )
        write_json(report, None)
    elif args.cmd == "apk-inventory":
        write_json(apk_inventory(args.apk), args.json_out)
    elif args.cmd == "apk-replace-entry":
        write_json(apk_replace_entry(args.apk, args.entry, args.replacement, args.out), None)
    elif args.cmd == "scan-text":
        write_json(scan_text_path(args.path), args.json_out)
    elif args.cmd == "device-probe":
        write_json(device_probe(args.app, args.target, args.out_dir), None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
