#!/usr/bin/env python3
"""Run static APK checks and optional ADB cold-start smoke tests for a rebuilt APK."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

from lib.axml import manifest_summary
from lib.dex import descriptor_to_dot, validate_dex_bytes


FATAL_PATTERNS = (
    "FATAL EXCEPTION",
    "JNI_ERR",
    "ClassNotFoundException",
    "VerifyError",
    "UnsatisfiedLinkError",
    "No implementation found",
    "Fatal signal",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def adb_command(adb: str, serial: str | None, arguments: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [adb]
    if serial:
        command.extend(["-s", serial])
    command.extend(arguments)
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if check and result.returncode:
        raise RuntimeError(f"ADB command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Report directory")
    parser.add_argument("--apksigner", help="Optional apksigner path for signature verification")
    parser.add_argument("--zipalign", help="Optional zipalign path for alignment verification")
    parser.add_argument("--package", help="Enable ADB smoke testing for this package")
    parser.add_argument("--launch-activity", help="Explicit component passed to am start -n")
    parser.add_argument("--launch-action", default="android.intent.action.MAIN", help="Action used with --launch-activity")
    parser.add_argument("--launch-category", default="android.intent.category.LAUNCHER", help="Category used with --launch-activity")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--cold-launches", type=int, default=3)
    parser.add_argument("--alive-seconds", type=int, default=20)
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--clean-install", action="store_true", help="Uninstall the package before install; this clears app data")
    parser.add_argument("--include-tool-output", action="store_true", help="Store complete apksigner and zipalign output in verification.json")
    return parser.parse_args()


def tool_output(value: str, include_full: bool) -> dict[str, object]:
    if include_full:
        return {"output": value}
    return {"output_tail": "\n".join(value.splitlines()[-40:])}


def static_check(apk: Path, apksigner: str | None, zipalign: str | None, include_tool_output: bool) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    dex_records: list[dict[str, object]] = []
    classes: set[str] = set()
    try:
        with zipfile.ZipFile(apk, "r") as archive:
            broken = archive.testzip()
            if broken:
                errors.append(f"corrupt ZIP entry: {broken}")
            names = [item.filename for item in archive.infolist()]
            duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
            if duplicates:
                errors.append("duplicate ZIP entries: " + ", ".join(duplicates[:10]))
            if "AndroidManifest.xml" not in names:
                errors.append("AndroidManifest.xml is missing")
                manifest: dict[str, object] = {}
            else:
                try:
                    manifest = manifest_summary(archive.read("AndroidManifest.xml"))
                except ValueError as exc:
                    manifest = {"error": str(exc)}
                    errors.append(f"manifest parse error: {exc}")
            def dex_order(name: str) -> int:
                match = re.fullmatch(r"classes(\d*)\.dex", Path(name).name)
                return 1 if match and not match.group(1) else int(match.group(1)) if match else 9999

            dex_names = sorted((name for name in names if Path(name).name.startswith("classes") and name.endswith(".dex")), key=dex_order)
            if not dex_names:
                errors.append("APK has no classes*.dex entries")
            for name in dex_names:
                report = validate_dex_bytes(archive.read(name))
                dex_records.append({"entry": name, **report.as_dict(include_classes=False)})
                if not report.valid:
                    errors.append(f"invalid {name}: {'; '.join(report.errors)}")
                for descriptor in report.classes:
                    dot_name = descriptor_to_dot(descriptor)
                    if dot_name in classes:
                        warnings.append(f"duplicate class definition: {dot_name}")
                    classes.add(dot_name)
            application = manifest.get("application") if isinstance(manifest, dict) else None
            package = manifest.get("package") if isinstance(manifest, dict) else None
            if isinstance(application, str) and application:
                resolved = application
                if application.startswith(".") and isinstance(package, str):
                    resolved = package + application
                elif "." not in application and isinstance(package, str):
                    resolved = package + "." + application
                if resolved not in classes:
                    warnings.append(f"manifest Application is not defined in output DEX: {resolved}")
    except zipfile.BadZipFile as exc:
        return {"valid": False, "errors": [f"not a valid ZIP/APK: {exc}"], "warnings": [], "dex": []}

    signature: dict[str, object] = {"checked": False, "valid": None}
    if apksigner:
        result = subprocess.run([apksigner, "verify", "--verbose", "--print-certs", str(apk)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        signature = {"checked": True, "valid": result.returncode == 0, **tool_output(result.stdout, include_tool_output)}
        if result.returncode:
            errors.append("apksigner verification failed")
    alignment: dict[str, object] = {"checked": False, "valid": None}
    if zipalign:
        result = subprocess.run([zipalign, "-c", "-v", "4", str(apk)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        alignment = {"checked": True, "valid": result.returncode == 0, **tool_output(result.stdout, include_tool_output)}
        if result.returncode:
            errors.append("zipalign verification failed")
    return {
        "valid": not errors,
        "apk": str(apk.resolve()),
        "sha256": sha256_file(apk),
        "manifest": manifest,
        "dex": dex_records,
        "class_count": len(classes),
        "errors": errors,
        "warnings": warnings,
        "signature": signature,
        "alignment": alignment,
    }


def device_smoke(args: argparse.Namespace, report_dir: Path) -> dict[str, object]:
    assert args.package
    errors: list[str] = []
    launches: list[dict[str, object]] = []
    try:
        if args.skip_install:
            installed = adb_command(args.adb, args.serial, ["shell", "pm", "path", args.package], check=False).stdout.strip()
            if not installed:
                return {
                    "enabled": True,
                    "package": args.package,
                    "launches": [],
                    "errors": ["package is not installed; omit --skip-install or install the APK first"],
                    "valid": False,
                }
        if args.clean_install:
            adb_command(args.adb, args.serial, ["uninstall", args.package], check=False)
        if not args.skip_install:
            adb_command(args.adb, args.serial, ["install", "-r", str(args.apk)])
        adb_command(args.adb, args.serial, ["shell", "logcat", "-b", "all", "-c"])
        for index in range(args.cold_launches):
            adb_command(args.adb, args.serial, ["shell", "am", "force-stop", args.package])
            if args.launch_activity:
                launch = adb_command(
                    args.adb,
                    args.serial,
                    [
                        "shell",
                        "am",
                        "start",
                        "-a",
                        args.launch_action,
                        "-c",
                        args.launch_category,
                        "-n",
                        args.launch_activity,
                    ],
                    check=False,
                )
            else:
                launch = adb_command(args.adb, args.serial, ["shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1"], check=False)
            time.sleep(args.alive_seconds)
            pid = adb_command(args.adb, args.serial, ["shell", "pidof", args.package], check=False).stdout.strip()
            top = adb_command(args.adb, args.serial, ["shell", "dumpsys", "activity", "activities"], check=False).stdout
            launches.append({"iteration": index + 1, "launch_output": launch.stdout, "pid": pid, "top_activity_dump": top[-6000:]})
            if launch.returncode or not pid:
                errors.append(f"cold launch {index + 1} did not leave a running process")
        logcat = adb_command(args.adb, args.serial, ["shell", "logcat", "-b", "all", "-d", "-t", "3000", "-v", "threadtime"], check=False).stdout
        (report_dir / "launch.log").write_text(logcat, encoding="utf-8")
        pids = {pid for launch in launches for pid in str(launch.get("pid", "")).split() if pid.isdigit()}
        pid_pattern = re.compile(r"\s(?:" + "|".join(re.escape(pid) for pid in pids) + r")\s") if pids else None
        lines = logcat.splitlines()
        relevant: set[int] = set()
        for line_index, line in enumerate(lines):
            if args.package not in line and not (pid_pattern and pid_pattern.search(line)):
                continue
            relevant.update(range(max(0, line_index - 16), min(len(lines), line_index + 120)))
        target_log = "\n".join(lines[index] for index in sorted(relevant))
        (report_dir / "target-launch.log").write_text(target_log, encoding="utf-8")
        hits = [pattern for pattern in FATAL_PATTERNS if pattern in target_log]
        if hits:
            errors.append("fatal log patterns: " + ", ".join(hits))
        remote_png = "/sdcard/yingan_rehydration_smoke.png"
        if adb_command(args.adb, args.serial, ["shell", "screencap", "-p", remote_png], check=False).returncode == 0:
            adb_command(args.adb, args.serial, ["pull", remote_png, str(report_dir / "smoke.png")], check=False)
        remote_xml = "/sdcard/yingan_rehydration_ui.xml"
        if adb_command(args.adb, args.serial, ["shell", "uiautomator", "dump", remote_xml], check=False).returncode == 0:
            adb_command(args.adb, args.serial, ["pull", remote_xml, str(report_dir / "ui.xml")], check=False)
    except RuntimeError as exc:
        errors.append(str(exc))
    return {"enabled": True, "package": args.package, "launches": launches, "errors": errors, "valid": not errors}


def main() -> int:
    args = parse_args()
    if not args.apk.is_file():
        raise SystemExit(f"APK not found: {args.apk}")
    if args.package and (args.cold_launches < 1 or args.alive_seconds < 3):
        raise SystemExit("device smoke requires at least one cold launch and three alive seconds")
    args.out.mkdir(parents=True, exist_ok=True)
    static = static_check(args.apk, args.apksigner, args.zipalign, args.include_tool_output)
    report: dict[str, object] = {"tool": "verify_rehydration", "static": static}
    if args.package:
        report["device"] = device_smoke(args, args.out)
    (args.out / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print((args.out / "verification.json").resolve())
    return 0 if static.get("valid") and (not args.package or report["device"].get("valid")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
