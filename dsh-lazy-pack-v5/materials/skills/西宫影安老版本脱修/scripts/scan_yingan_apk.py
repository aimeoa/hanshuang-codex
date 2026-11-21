#!/usr/bin/env python3
"""Inventory an APK and emit evidence for the YingAn/YingPo recovery workflow."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

from lib.axml import manifest_summary
from lib.dex import validate_dex_bytes


SHELL_MARKERS = (
    "strEntryApplication",
    "startApp",
    "abcd655",
    "abcdstr",
    "System.load",
    "System.exit",
    "loadClass",
)
MAX_EMBEDDED_DEX_SIZE = 256 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def output_file(path: Path) -> Path:
    if path.suffix.lower() == ".json":
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    path.mkdir(parents=True, exist_ok=True)
    return path / "scan.json"


def write_json(path: Path, value: object) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def entry_is_dex(name: str) -> bool:
    return bool(re.fullmatch(r"classes(?:\d+)?\.dex", Path(name).name))


def scan_embedded_dex(entry_name: str, data: bytes, extract_dir: Path | None) -> list[dict[str, object]]:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return []
    results: list[dict[str, object]] = []
    with zipfile.ZipFile(io.BytesIO(data), "r") as container:
        for nested in container.infolist():
            if nested.is_dir() or not entry_is_dex(nested.filename):
                continue
            if nested.file_size > MAX_EMBEDDED_DEX_SIZE:
                results.append({"entry": nested.filename, "error": "embedded DEX exceeds size limit"})
                continue
            dex = container.read(nested)
            record: dict[str, object] = {
                "entry": nested.filename,
                "size": len(dex),
                "sha256": sha256_bytes(dex),
                "validation": validate_dex_bytes(dex).as_dict(include_classes=False),
            }
            if extract_dir is not None:
                prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", entry_name)
                target = extract_dir / prefix / Path(nested.filename).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(dex)
                record["extracted_to"] = str(target.resolve())
            results.append(record)
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True, help="Source APK")
    parser.add_argument("--out", type=Path, required=True, help="Report JSON path or report directory")
    parser.add_argument("--extract-dir", type=Path, help="Optional directory for DEX found inside ZIP-shaped native entries")
    parser.add_argument("--no-embedded-extract", action="store_true", help="Do not inspect embedded ZIP containers")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"APK not found: {args.apk}")
    report_path = output_file(args.out)
    extract_dir = None if args.no_embedded_extract else args.extract_dir
    if extract_dir is not None:
        extract_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, object] = {
        "tool": "scan_yingan_apk",
        "apk": {"path": str(args.apk.resolve()), "size": args.apk.stat().st_size, "sha256": sha256_file(args.apk)},
        "manifest": None,
        "dex": [],
        "embedded_dex": [],
        "native_libraries": [],
        "assets": [],
        "signature_entries": [],
        "duplicate_entries": [],
        "signals": [],
    }

    with zipfile.ZipFile(args.apk, "r") as archive:
        names = [item.filename for item in archive.infolist()]
        duplicate_entries = sorted({name for name in names if names.count(name) > 1})
        result["duplicate_entries"] = duplicate_entries
        if "AndroidManifest.xml" not in names:
            raise SystemExit("APK has no AndroidManifest.xml")
        manifest_data = archive.read("AndroidManifest.xml")
        try:
            result["manifest"] = manifest_summary(manifest_data)
        except ValueError as exc:
            result["manifest"] = {"error": str(exc), "sha256": sha256_bytes(manifest_data)}

        root_dex = b""
        for item in archive.infolist():
            name = item.filename
            if entry_is_dex(name):
                dex = archive.read(item)
                record = {
                    "entry": name,
                    "size": len(dex),
                    "sha256": sha256_bytes(dex),
                    "validation": validate_dex_bytes(dex).as_dict(include_classes=False),
                }
                result["dex"].append(record)
                if name == "classes.dex":
                    root_dex = dex
            elif name.startswith("lib/") and name.endswith(".so"):
                record = {"entry": name, "size": item.file_size, "sha256": sha256_bytes(archive.read(item))}
                result["native_libraries"].append(record)
                if not args.no_embedded_extract and ("shellservice_dex" in name or "shell" in name or zipfile.is_zipfile(io.BytesIO(archive.read(item)))):
                    extracted = scan_embedded_dex(name, archive.read(item), extract_dir)
                    if extracted:
                        result["embedded_dex"].append({"container": name, "dex": extracted})
            elif name.startswith("assets/"):
                result["assets"].append({"entry": name, "size": item.file_size})
            elif name.upper().startswith("META-INF/"):
                result["signature_entries"].append(name)

    signals: list[dict[str, object]] = []
    root_text = root_dex.decode("latin-1", errors="ignore")
    marker_hits = [marker for marker in SHELL_MARKERS if marker in root_text]
    if marker_hits:
        signals.append({"kind": "root_dex_callbacks", "weight": len(marker_hits), "evidence": marker_hits})
    root_validation = validate_dex_bytes(root_dex) if root_dex else None
    if root_validation and root_validation.valid and (root_validation.class_count or 0) <= 16:
        signals.append({"kind": "tiny_root_dex", "weight": 2, "evidence": {"class_count": root_validation.class_count}})
    native_names = [str(item["entry"]) for item in result["native_libraries"]]
    protector_names = [name for name in native_names if "libabcd" in name.lower() or "shellservice_dex" in name.lower()]
    if protector_names:
        signals.append({"kind": "native_loader", "weight": len(protector_names), "evidence": protector_names})
    asset_names = [str(item["entry"]) for item in result["assets"]]
    protected_assets = [name for name in asset_names if "protect" in name.lower() or name.lower().startswith("abcd/")]
    if protected_assets:
        signals.append({"kind": "protected_assets", "weight": len(protected_assets), "evidence": protected_assets})
    if result["embedded_dex"]:
        signals.append({"kind": "embedded_dex_container", "weight": len(result["embedded_dex"]), "evidence": [item["container"] for item in result["embedded_dex"]]})
    result["signals"] = signals
    result["family_score"] = sum(int(item["weight"]) for item in signals)
    result["classification"] = "yingan_like" if result["family_score"] >= 3 else "not_confirmed"

    write_json(report_path, result)
    print(report_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
