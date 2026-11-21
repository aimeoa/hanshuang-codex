#!/usr/bin/env python3
"""Rebuild a plan-approved multidex APK while preserving unknown non-DEX entries."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from lib.axml import manifest_summary, patch_application_name, patch_component_name
from lib.dex import validate_dex_path


SIGNATURE_SUFFIXES = (".SF", ".RSA", ".DSA", ".EC")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_info(source: zipfile.ZipInfo) -> zipfile.ZipInfo:
    target = zipfile.ZipInfo(source.filename, source.date_time)
    target.comment = source.comment
    target.extra = source.extra
    target.internal_attr = source.internal_attr
    target.external_attr = source.external_attr
    target.create_system = source.create_system
    target.create_version = source.create_version
    target.extract_version = source.extract_version
    target.flag_bits = source.flag_bits & ~0x08
    target.compress_type = source.compress_type
    return target


def is_signature_entry(name: str) -> bool:
    if not name.upper().startswith("META-INF/"):
        return False
    leaf = name.rsplit("/", 1)[-1].upper()
    return leaf == "MANIFEST.MF" or leaf.endswith(SIGNATURE_SUFFIXES)


def is_dex_entry(name: str) -> bool:
    leaf = Path(name).name
    if not leaf.startswith("classes") or not leaf.endswith(".dex"):
        return False
    middle = leaf[7:-4]
    return middle == "" or middle.isdigit()


def run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True, help="Unmodified APK that matches the plan source hash")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Final APK; unsigned when signing options are omitted")
    parser.add_argument("--report", type=Path, help="Build manifest JSON")
    parser.add_argument("--zipalign", help="Path to Android zipalign; omit to leave ZIP alignment unchanged")
    parser.add_argument("--apksigner", help="Path to Android apksigner")
    parser.add_argument("--keystore", type=Path, help="Signing keystore; required with --apksigner")
    parser.add_argument("--alias", default="rehydrate")
    parser.add_argument("--ks-pass", help="Keystore password")
    parser.add_argument("--key-pass", help="Key password; defaults to --ks-pass")
    parser.add_argument("--include-entry-list", action="store_true", help="Include every preserved ZIP entry in the build report")
    return parser.parse_args()


def load_plan(path: Path) -> dict[str, object]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema") != "yingan-recovery-plan/v1":
        raise ValueError("unsupported or missing recovery-plan schema")
    if not isinstance(plan.get("source"), dict) or not isinstance(plan.get("dex"), dict):
        raise ValueError("plan has no source or DEX section")
    return plan


def validated_dex(path_value: object, expected_hash: object) -> Path:
    path = Path(str(path_value))
    if not path.is_file():
        raise ValueError(f"DEX is missing: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(f"DEX hash changed after planning: {path}")
    report = validate_dex_path(path)
    if not report.valid:
        raise ValueError(f"DEX is invalid: {path}: {'; '.join(report.errors)}")
    return path


def main() -> int:
    args = parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"APK not found: {args.apk}")
    if bool(args.apksigner) != bool(args.keystore):
        raise SystemExit("--apksigner and --keystore must be supplied together")
    if args.apksigner and not args.ks_pass:
        raise SystemExit("--ks-pass is required when signing")
    plan = load_plan(args.plan)
    source = plan["source"]
    if sha256_file(args.apk) != source.get("sha256"):
        raise SystemExit("--apk does not match the source hash recorded in the plan")

    dex_plan = plan["dex"]
    root_plan = dex_plan.get("root")
    dex_paths: list[Path] = []
    if root_plan:
        if not isinstance(root_plan, dict):
            raise SystemExit("plan root DEX entry is malformed")
        dex_paths.append(validated_dex(root_plan.get("path"), root_plan.get("sha256")))
    runtime = dex_plan.get("runtime")
    if not isinstance(runtime, list):
        raise SystemExit("plan runtime DEX list is malformed")
    for item in runtime:
        if not isinstance(item, dict):
            raise SystemExit("plan runtime DEX item is malformed")
        dex_paths.append(validated_dex(item.get("path"), item.get("sha256")))
    if not dex_paths or len(dex_paths) > 99:
        raise SystemExit("plan must contain between one and 99 DEX files")

    manifest_plan = plan.get("manifest", {})
    packaging = plan.get("packaging", {})
    if not isinstance(manifest_plan, dict) or not isinstance(packaging, dict):
        raise SystemExit("plan manifest or packaging section is malformed")
    remove_entries = set(packaging.get("remove_entries", []))
    if any(name == "AndroidManifest.xml" or is_dex_entry(name) for name in remove_entries):
        raise SystemExit("plan may not remove the manifest or generated DEX entries")
    components = manifest_plan.get("components", [])
    if not isinstance(components, list):
        raise SystemExit("plan component list is malformed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report_path = args.report or args.out.with_suffix(args.out.suffix + ".build.json")
    copied_entries: list[str] = []
    copied_entry_count = 0
    removed_entries: list[str] = []
    with tempfile.TemporaryDirectory(prefix="yingan_rebuild_") as temp_dir:
        temp = Path(temp_dir)
        unsigned = temp / "recovered.unsigned.apk"
        aligned = temp / "recovered.aligned.apk"
        with zipfile.ZipFile(args.apk, "r") as original, zipfile.ZipFile(unsigned, "w", allowZip64=True) as rebuilt:
            manifest = original.read("AndroidManifest.xml")
            application = manifest_plan.get("application")
            if application:
                manifest = patch_application_name(manifest, str(application))
            for item in components:
                if not isinstance(item, dict):
                    raise SystemExit("plan component item is malformed")
                manifest = patch_component_name(manifest, str(item["element"]), str(item["from"]), str(item["to"]))
            manifest_summary(manifest)
            manifest_info = copy_info(original.getinfo("AndroidManifest.xml"))
            rebuilt.writestr(manifest_info, manifest)

            for entry in original.infolist():
                if entry.filename == "AndroidManifest.xml" or is_dex_entry(entry.filename) or is_signature_entry(entry.filename):
                    continue
                if entry.filename in remove_entries:
                    removed_entries.append(entry.filename)
                    continue
                rebuilt.writestr(copy_info(entry), original.read(entry))
                copied_entry_count += 1
                if args.include_entry_list:
                    copied_entries.append(entry.filename)
            for index, dex in enumerate(dex_paths, start=1):
                name = "classes.dex" if index == 1 else f"classes{index}.dex"
                rebuilt.writestr(name, dex.read_bytes(), compress_type=zipfile.ZIP_STORED)

        working = unsigned
        if args.zipalign:
            run([args.zipalign, "-f", "4", str(unsigned), str(aligned)])
            working = aligned
        signing = {"signed": False, "zipaligned": bool(args.zipalign)}
        if args.apksigner:
            key_pass = args.key_pass or args.ks_pass
            run(
                [
                    args.apksigner,
                    "sign",
                    "--ks",
                    str(args.keystore),
                    "--ks-key-alias",
                    args.alias,
                    "--ks-pass",
                    f"pass:{args.ks_pass}",
                    "--key-pass",
                    f"pass:{key_pass}",
                    "--out",
                    str(args.out),
                    str(working),
                ]
            )
            run([args.apksigner, "verify", "--verbose", "--print-certs", str(args.out)])
            signing["signed"] = True
        else:
            shutil.copyfile(working, args.out)

    with zipfile.ZipFile(args.out, "r") as output:
        broken = output.testzip()
        if broken:
            raise SystemExit(f"rebuilt APK contains a corrupt ZIP entry: {broken}")
        output_dexes = [item.filename for item in output.infolist() if is_dex_entry(item.filename)]
    result = {
        "tool": "rebuild_rehydrated_apk",
        "plan": str(args.plan.resolve()),
        "source_apk": str(args.apk.resolve()),
        "output_apk": str(args.out.resolve()),
        "output_sha256": sha256_file(args.out),
        "dex_entries": output_dexes,
        "copied_entry_count": copied_entry_count,
        "removed_entries": removed_entries,
        "signing": signing,
    }
    if args.include_entry_list:
        result["copied_entries"] = copied_entries
    write_json(report_path, result)
    print(args.out.resolve())
    print(report_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
