#!/usr/bin/env python3
"""Resolve manifest components against an ordered, validated runtime DEX set."""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from lib.axml import manifest_summary
from lib.dex import DexView, descriptor_to_dot


APPLICATION_BASE = "android.app.Application"
ACTIVITY_BASES = {
    "android.app.Activity",
    "androidx.activity.ComponentActivity",
    "androidx.fragment.app.FragmentActivity",
    "androidx.appcompat.app.AppCompatActivity",
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def output_file(path: Path) -> Path:
    if path.suffix.lower() == ".json":
        return path
    return path / "graph.json"


def canonical_name(package: str, name: str | None) -> str | None:
    if not name:
        return None
    if name.startswith("."):
        return f"{package}{name}"
    if "." not in name:
        return f"{package}.{name}"
    return name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True, help="Output of validate_dex_set.py")
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"APK not found: {args.apk}")
    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    records = validation.get("dex")
    if not isinstance(records, list):
        raise SystemExit("validation report has no dex records")
    with zipfile.ZipFile(args.apk, "r") as archive:
        manifest = manifest_summary(archive.read("AndroidManifest.xml"))
    package = str(manifest.get("package", ""))

    classes: dict[str, dict[str, object]] = {}
    sources: dict[str, list[int]] = {}
    read_errors: list[dict[str, object]] = []
    for record in records:
        if not record.get("valid"):
            continue
        source = Path(str(record["path"]))
        try:
            definitions = DexView(source.read_bytes()).class_definitions()
        except (OSError, ValueError, IndexError) as exc:
            read_errors.append({"path": str(source), "error": str(exc)})
            continue
        order = int(record["order"])
        for definition in definitions:
            name = str(definition["name"])
            sources.setdefault(name, []).append(order)
            classes.setdefault(name, {**definition, "order": order})

    def is_subclass(name: str, target: str) -> bool:
        visited: set[str] = set()
        current = name
        for _ in range(96):
            if current == target:
                return True
            if current in visited:
                return False
            visited.add(current)
            definition = classes.get(current)
            if not definition:
                return False
            parent = definition.get("super_name")
            if not isinstance(parent, str):
                return False
            current = parent
        return False

    applications = sorted(name for name in classes if is_subclass(name, APPLICATION_BASE) and name != APPLICATION_BASE)
    activities = sorted(
        name
        for name in classes
        if name not in ACTIVITY_BASES and any(is_subclass(name, base) for base in ACTIVITY_BASES)
    )
    component_rows: list[dict[str, object]] = []
    components = manifest.get("components", {})
    if isinstance(components, dict):
        for element, values in components.items():
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                raw_name = str(item.get("name", ""))
                canonical = canonical_name(package, raw_name)
                component_rows.append(
                    {
                        "element": element,
                        "manifest_name": raw_name,
                        "class_name": canonical,
                        "resolved": canonical in classes,
                        "target_activity": canonical_name(package, str(item["targetActivity"])) if "targetActivity" in item else None,
                    }
                )
    manifest_application = canonical_name(package, manifest.get("application") if isinstance(manifest.get("application"), str) else None)
    core_pairs = sorted(
        {
            (name, str(definition["super_name"]))
            for name, definition in classes.items()
            if isinstance(definition.get("super_name"), str) and str(definition["super_name"]).endswith("Core")
        }
    )
    result = {
        "tool": "inspect_runtime_graph",
        "manifest": manifest,
        "manifest_application": {"class_name": manifest_application, "resolved": manifest_application in classes if manifest_application else False},
        "components": component_rows,
        "application_candidates": applications,
        "activity_candidates": activities,
        "possible_wrapper_core_pairs": [{"wrapper": wrapper, "core": core} for wrapper, core in core_pairs],
        "duplicate_class_sources": [{"class_name": name, "orders": orders} for name, orders in sorted(sources.items()) if len(orders) > 1],
        "class_count": len(classes),
        "read_errors": read_errors,
    }
    target = output_file(args.out)
    write_json(target, result)
    print(target.resolve())
    return 0 if not read_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
