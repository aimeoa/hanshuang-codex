#!/usr/bin/env python3
"""Validate recovered DEX files, preserve their observed order, and report collisions."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from lib.dex import validate_dex_path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def read_capture_paths(path: Path) -> list[Path]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("dex", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("capture JSON must be a list or contain a dex list")
    result: list[Path] = []
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        candidate = Path(item["path"])
        result.append(candidate if candidate.is_absolute() else path.parent / candidate)
    if not result:
        raise ValueError("capture JSON has no DEX paths")
    return result


def output_file(path: Path) -> Path:
    if path.suffix.lower() == ".json":
        return path
    return path / "dex-validation.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dex", type=Path, action="append", help="Recovered DEX, repeated in observed load order")
    parser.add_argument("--dex-dir", type=Path, help="Directory of DEX files; lexical order is used only when no capture manifest exists")
    parser.add_argument("--capture-json", type=Path, help="Capture manifest that supplies the observed DEX order")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-class-collisions", action="store_true", help="Write a successful report even when different DEX files define the same class")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources: list[Path] = []
    if args.capture_json:
        sources.extend(read_capture_paths(args.capture_json))
    if args.dex:
        sources.extend(args.dex)
    if args.dex_dir:
        if not args.dex_dir.is_dir():
            raise SystemExit(f"DEX directory not found: {args.dex_dir}")
        sources.extend(sorted(args.dex_dir.glob("*.dex")))
    if not sources:
        raise SystemExit("provide --capture-json, --dex, or --dex-dir")

    records: list[dict[str, object]] = []
    classes: dict[str, list[int]] = {}
    hashes: dict[str, list[int]] = {}
    invalid = False
    for order, source in enumerate(sources):
        if not source.is_file():
            record: dict[str, object] = {"order": order, "path": str(source), "valid": False, "errors": ["file does not exist"]}
            invalid = True
        else:
            report = validate_dex_path(source)
            record = {"order": order, "path": str(source.resolve()), **report.as_dict(include_classes=True)}
            invalid = invalid or not report.valid
            if report.valid:
                hashes.setdefault(report.sha256, []).append(order)
                for descriptor in report.classes:
                    classes.setdefault(descriptor, []).append(order)
        records.append(record)

    exact_duplicates = [
        {"sha256": digest, "orders": orders}
        for digest, orders in hashes.items()
        if len(orders) > 1
    ]
    collisions: list[dict[str, object]] = []
    for descriptor, orders in sorted(classes.items()):
        source_hashes = {str(records[index].get("sha256", "")) for index in orders}
        if len(source_hashes) > 1:
            collisions.append({"descriptor": descriptor, "orders": orders, "paths": [records[index]["path"] for index in orders]})
    result = {
        "tool": "validate_dex_set",
        "dex": records,
        "exact_duplicate_images": exact_duplicates,
        "class_collisions": collisions,
        "valid": not invalid and (args.allow_class_collisions or not collisions),
        "order_source": "capture-json" if args.capture_json else "explicit-or-directory",
    }
    target = output_file(args.out)
    write_json(target, result)
    print(target.resolve())
    if invalid:
        return 2
    if collisions and not args.allow_class_collisions:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
