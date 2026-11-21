from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "hikari_runtime_image.py"
ABLATION = ROOT / "scripts" / "hikari_patch_ablation.py"
STATIC = ROOT / "scripts" / "hikari_static_rewrite.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], text=True, encoding="utf-8", capture_output=True, check=False,
    )


def write_elf64(path: Path) -> None:
    data = bytearray(0x200)
    data[:16] = b"\x7fELF\x02\x01\x01\0" + b"\0" * 8
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, 3, 183, 1, 0, 64, 0, 0, 64, 56, 0, 0, 0, 0)
    path.write_bytes(data)


def write_elf64_with_post_load_tail(path: Path, overlay: bytes = b"") -> None:
    data = bytearray(0x380)
    data[:16] = b"\x7fELF\x02\x01\x01\0" + b"\0" * 8
    struct.pack_into(
        "<HHIQQQIHHHHHH", data, 16,
        3, 183, 1, 0, 64, 0x300, 0, 64, 56, 1, 64, 2, 1,
    )
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 0x100, 0x100, 0x1000)
    names = b"\0.shstrtab\0"
    data[0x280:0x280 + len(names)] = names
    struct.pack_into("<IIQQQQIIQQ", data, 0x340, 1, 3, 0, 0, 0x280, len(names), 0, 0, 1, 0)
    path.write_bytes(data + overlay)


class FunkHikariToolsTests(unittest.TestCase):
    def test_rebuild_strings_carrier_and_extract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            capture = root / "capture"
            capture.mkdir()
            base, end = 0x100000, 0x104000
            rx = bytearray(0x1000)
            rx[0x100:0x100 + len("版本检查".encode()) + 1] = "版本检查".encode() + b"\0"
            rw = bytearray(0x1000)
            struct.pack_into("<Q", rw, 0x20, base + 0x100)
            embedded = root / "embedded.elf"
            write_elf64(embedded)
            rw[0x100:0x300] = embedded.read_bytes()
            records = []
            for start, perms, name, data in (
                (base, "r-xp", "", bytes(rx)),
                (base + 0x3000, "rw-p", "[anon:.bss]", bytes(rw)),
            ):
                filename = f"{start:016x}-{start + len(data):016x}.bin"
                (capture / filename).write_bytes(data)
                records.append({
                    "start": hex(start), "end": hex(start + len(data)), "size": len(data),
                    "perms": perms, "offset": "0x0", "name": name, "status": "CAPTURED",
                    "file": filename, "sha256": sha256(data),
                })
            maps = b"100000-101000 r-xp 00000000 00:00 0\n103000-104000 rw-p 00000000 00:00 0 [anon:.bss]\n"
            (capture / "maps.txt").write_bytes(maps)
            (capture / "capture.json").write_text(json.dumps({
                "pid": 1234, "cmdline_hex": b"fixture\0".hex(),
                "executable": {"resolved_path": "/fixture", "sha256": "a" * 64, "identity_bound": True},
                "maps_sha256": sha256(maps), "mappings": records,
            }), encoding="utf-8")
            capture_copy = root / "capture-copy"
            shutil.copytree(capture, capture_copy)
            compared = run(str(RUNTIME), "compare-captures", str(capture), str(capture_copy))
            self.assertEqual(compared.returncode, 0, compared.stderr)
            comparison = json.loads(compared.stdout)
            self.assertTrue(comparison["capture_integrity_equal"])
            self.assertTrue(comparison["executable_sha256_equal"])
            self.assertEqual(comparison["left_maps"]["match_mode"], "exact")
            legacy_maps = (capture_copy / "maps.txt").read_bytes().replace(b"\n", b"\r\n")
            (capture_copy / "maps.txt").write_bytes(legacy_maps)
            compared = run(str(RUNTIME), "compare-captures", str(capture), str(capture_copy))
            self.assertEqual(compared.returncode, 0, compared.stderr)
            self.assertEqual(json.loads(compared.stdout)["right_maps"]["match_mode"], "legacy-crlf-normalized")
            copied_report_path = capture_copy / "capture.json"
            copied_report = json.loads(copied_report_path.read_text(encoding="utf-8"))
            changed_path = capture_copy / copied_report["mappings"][0]["file"]
            changed = bytearray(changed_path.read_bytes())
            changed[0] ^= 0xFF
            changed_path.write_bytes(changed)
            copied_report["mappings"][0]["sha256"] = sha256(bytes(changed))
            copied_report_path.write_text(json.dumps(copied_report), encoding="utf-8")
            compared = run(str(RUNTIME), "compare-captures", str(capture), str(capture_copy))
            self.assertEqual(compared.returncode, 1, compared.stderr)
            self.assertFalse(json.loads(compared.stdout)["all_mapping_hashes_equal"])
            prefix = root / "inner"
            rebuilt = run(str(RUNTIME), "rebuild", str(capture), "--base", hex(base), "--end", hex(end), "--out-prefix", str(prefix), "--normalize-pointers")
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            manifest = json.loads(prefix.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["raw_memory"]["size"], end - base)
            self.assertEqual(manifest["analysis_elf"]["pointer_normalizations"], 1)
            self.assertEqual(manifest["embedded_elf_candidates"][0]["relative_offset"], "0x3100")
            raw_image = prefix.with_suffix(".mem").read_bytes()
            self.assertEqual(raw_image[0x2000:0x3000], b"\0" * 0x1000)
            self.assertEqual(prefix.with_suffix(".analysis.elf").read_bytes()[:4], b"\x7fELF")

            strings_prefix = root / "strings"
            strings = run(str(RUNTIME), "strings", str(prefix.with_suffix(".mem")), "--out-prefix", str(strings_prefix))
            self.assertEqual(strings.returncode, 0, strings.stderr)
            pool = json.loads(strings_prefix.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertIn("版本检查", {item["text"] for item in pool["strings"]})

            outer = root / "outer.elf"
            write_elf64(outer)
            carrier = root / "carrier.elf"
            carrier_manifest = root / "carrier.json"
            packaged = run(
                str(RUNTIME), "carrier", str(outer), str(prefix.with_suffix(".mem")),
                "--runtime-base", hex(base), "--runtime-end", hex(end),
                "--output", str(carrier), "--manifest", str(carrier_manifest),
            )
            self.assertEqual(packaged.returncode, 0, packaged.stderr)
            verified = run(
                str(RUNTIME), "verify-carrier", str(carrier), "--manifest", str(carrier_manifest),
                "--needle", "版本检查",
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            outer_out, inner_out = root / "outer.out", root / "inner.out"
            extracted = run(
                str(RUNTIME), "extract-carrier", str(carrier), "--manifest", str(carrier_manifest),
                "--outer-out", str(outer_out), "--inner-out", str(inner_out),
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            self.assertEqual(outer_out.read_bytes(), outer.read_bytes())
            self.assertEqual(inner_out.read_bytes(), raw_image)

    def test_inspect_distinguishes_post_load_tail_from_true_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            represented = root / "represented.elf"
            write_elf64_with_post_load_tail(represented)
            report_dir = root / "represented-report"
            result = run(str(STATIC), str(represented), "--inspect", "--report-dir", str(report_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            layout = json.loads(result.stdout)["layout"]
            self.assertEqual(layout["post_load_tail_size"], 0x280)
            self.assertEqual(layout["represented_file_end"], "0x380")
            self.assertEqual(layout["overlay_size"], 0)

            with_overlay = root / "overlay.elf"
            write_elf64_with_post_load_tail(with_overlay, b"PAYLOAD")
            report_dir = root / "overlay-report"
            result = run(str(STATIC), str(with_overlay), "--inspect", "--report-dir", str(report_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            layout = json.loads(result.stdout)["layout"]
            self.assertEqual(layout["represented_file_end"], "0x380")
            self.assertEqual(layout["overlay_size"], len(b"PAYLOAD"))

    def test_patch_ablation_rejects_bad_extra_and_keeps_good_extra(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sample = root / "sample.bin"
            sample.write_bytes(b"AAAA")
            baseline = root / "baseline.json"
            candidate = root / "candidate.json"
            baseline.write_text(json.dumps({"patches": []}), encoding="utf-8")
            candidate.write_text(json.dumps({"patches": [
                {"file_offset": "0x0", "size": 1, "old_bytes": "41", "new_bytes": "58", "va": "0x0"},
                {"file_offset": "0x1", "size": 1, "old_bytes": "41", "new_bytes": "42", "va": "0x1"},
            ]}), encoding="utf-8")
            validator = root / "validator.py"
            validator.write_text(
                "import pathlib,sys\nsys.exit(0 if pathlib.Path(sys.argv[1]).read_bytes()[:1] == b'A' else 1)\n",
                encoding="utf-8",
            )
            output, report = root / "final.bin", root / "report.json"
            command = f'"{sys.executable}" "{validator}" {{artifact}}'
            result = run(
                str(ABLATION), "--root", str(sample), "--baseline-manifest", str(baseline),
                "--candidate-manifest", str(candidate), "--validator", command,
                "--out", str(output), "--report", str(report),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), b"ABAA")
            document = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(document["accepted_extra_count"], 1)
            self.assertEqual(document["rejected_extra_count"], 1)
            self.assertTrue(document["rollback_matches_root"])


if __name__ == "__main__":
    unittest.main()
