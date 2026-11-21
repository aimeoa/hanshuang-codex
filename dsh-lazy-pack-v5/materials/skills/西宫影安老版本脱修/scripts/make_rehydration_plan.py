#!/usr/bin/env python3
"""Create the declarative input consumed by rebuild_rehydrated_apk.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from lib.dex import validate_dex_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def parse_component(value: str) -> dict[str, str]:
    try:
        element, pair = value.split(":", 1)
        original, replacement = pair.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("component format is element:old.name=new.name") from exc
    if element not in {"activity", "activity-alias", "service", "receiver", "provider"}:
        raise argparse.ArgumentTypeError(f"unsupported manifest component type: {element}")
    if not original or not replacement:
        raise argparse.ArgumentTypeError("component original and replacement names are required")
    return {"element": element, "from": original, "to": replacement}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True, help="scan_yingan_apk.py JSON")
    parser.add_argument("--validation", type=Path, required=True, help="validate_dex_set.py JSON")
    parser.add_argument("--graph", type=Path, required=True, help="inspect_runtime_graph.py JSON")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root-dex", type=Path, help="Optional managed classes.dex that remains the primary DEX")
    parser.add_argument("--application", help="Real Application class to write to the manifest")
    parser.add_argument("--component", action="append", type=parse_component, default=[], help="element:old.name=new.name; repeat as needed")
    parser.add_argument("--remove-entry", action="append", default=[], help="Explicit APK ZIP entry to remove only after compatibility validation")
    parser.add_argument("--launch-activity", help="Expected resumed activity for device smoke tests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scan = json.loads(args.scan.read_text(encoding="utf-8"))
    validation = json.loads(args.validation.read_text(encoding="utf-8"))
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    apk_info = scan.get("apk")
    if not isinstance(apk_info, dict) or not isinstance(apk_info.get("path"), str):
        raise SystemExit("scan report has no source APK")
    source_apk = Path(apk_info["path"])
    if not source_apk.is_file():
        raise SystemExit(f"source APK referenced by scan report no longer exists: {source_apk}")
    actual_hash = sha256_file(source_apk)
    if actual_hash != apk_info.get("sha256"):
        raise SystemExit("source APK hash changed since the scan report was created")
    if not validation.get("valid"):
        raise SystemExit("DEX validation is not clean; resolve invalid DEX or duplicate classes before planning")
    if validation.get("class_collisions"):
        raise SystemExit("DEX class collisions cannot be rebuilt until the runtime set is narrowed to one definition per class")

    runtime_dex: list[dict[str, object]] = []
    for record in validation.get("dex", []):
        if not isinstance(record, dict) or not record.get("valid"):
            raise SystemExit("plan input contains an invalid DEX record")
        path = Path(str(record["path"]))
        if not path.is_file():
            raise SystemExit(f"recovered DEX is missing: {path}")
        if sha256_file(path) != record.get("sha256"):
            raise SystemExit(f"recovered DEX changed since validation: {path}")
        runtime_dex.append({"order": int(record["order"]), "path": str(path.resolve()), "sha256": str(record["sha256"])})
    if not runtime_dex:
        raise SystemExit("no validated recovered DEX files are available")
    runtime_dex.sort(key=lambda item: int(item["order"]))

    root: dict[str, str] | None = None
    if args.root_dex:
        report = validate_dex_path(args.root_dex)
        if not report.valid:
            raise SystemExit(f"root DEX is invalid: {'; '.join(report.errors)}")
        root = {"path": str(args.root_dex.resolve()), "sha256": report.sha256}

    selected_application = args.application
    selection_reason = "explicit" if selected_application else "preserve-manifest"
    current_application = graph.get("manifest_application", {})
    if not selected_application and isinstance(current_application, dict) and current_application.get("resolved"):
        selected_application = None
    elif not selected_application:
        candidates = graph.get("application_candidates", [])
        if isinstance(candidates, list) and len(candidates) == 1:
            selected_application = str(candidates[0])
            selection_reason = "only-runtime-application-candidate"
        else:
            selection_reason = "unresolved-requires-explicit-selection"

    manifest = scan.get("manifest", {})
    package_name = manifest.get("package") if isinstance(manifest, dict) else None
    plan = {
        "schema": "yingan-recovery-plan/v1",
        "source": {"apk": str(source_apk.resolve()), "sha256": actual_hash},
        "dex": {"root": root, "runtime": runtime_dex},
        "manifest": {
            "application": selected_application,
            "application_selection": selection_reason,
            "components": args.component,
        },
        "packaging": {
            "mode": "compatibility",
            "preserve_all_non_dex_entries": True,
            "remove_entries": sorted(set(args.remove_entry)),
        },
        "verification": {
            "package": package_name,
            "launch_activity": args.launch_activity,
            "cold_launches": 3,
            "minimum_alive_seconds": 20,
        },
        "evidence": {
            "scan": str(args.scan.resolve()),
            "validation": str(args.validation.resolve()),
            "graph": str(args.graph.resolve()),
        },
    }
    write_json(args.out, plan)
    print(args.out.resolve())
    if selection_reason == "unresolved-requires-explicit-selection":
        print("plan created without an Application change; pass --application after confirming the real runtime Application")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
