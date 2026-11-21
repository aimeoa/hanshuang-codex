import os
import sys
import json
import zipfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import xg_elf_tool as tool


def make_fake_elf64(path: Path):
    data = bytearray(0x3000)
    data[0:4] = b"\x7fELF"
    data[4] = 2
    data[5] = 1
    data[6] = 1
    data[0x10:0x12] = (2).to_bytes(2, "little")
    data[0x12:0x14] = (0xB7).to_bytes(2, "little")
    data[0x18:0x20] = (0x1000).to_bytes(8, "little")
    data[0x20:0x28] = (0x40).to_bytes(8, "little")
    data[0x34:0x36] = (64).to_bytes(2, "little")
    data[0x36:0x38] = (56).to_bytes(2, "little")
    data[0x38:0x3A] = (1).to_bytes(2, "little")
    ph = 0x40
    data[ph:ph+4] = (1).to_bytes(4, "little")
    data[ph+8:ph+16] = (0x1000).to_bytes(8, "little")
    data[ph+16:ph+24] = (0x400000).to_bytes(8, "little")
    data[ph+32:ph+40] = (0x1000).to_bytes(8, "little")
    data[0x1234:0x1238] = bytes.fromhex("11223344")
    path.write_bytes(data)


class XgElfToolTests(unittest.TestCase):
    def test_va_to_offset_uses_pt_load_segments(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.elf"
            make_fake_elf64(p)
            elf = tool.parse_elf(p)
            self.assertEqual(tool.va_to_offset(elf["segments"], 0x400234), 0x1234)

    def test_patch_bytes_requires_expected_bytes_and_preserves_headers(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "a.elf"
            out = Path(td) / "b.elf"
            make_fake_elf64(src)
            report = tool.patch_bytes(src, out, 0x400234, bytes.fromhex("11223344"), bytes.fromhex("aabbccdd"))
            self.assertTrue(report["verify"]["elf_header_unchanged"])
            self.assertTrue(report["verify"]["program_headers_unchanged"])
            self.assertEqual(out.read_bytes()[0x1234:0x1238], bytes.fromhex("aabbccdd"))
            with self.assertRaises(ValueError):
                tool.patch_bytes(src, Path(td) / "bad.elf", 0x400234, bytes.fromhex("00000000"), bytes.fromhex("aabbccdd"))

    def test_apk_replace_entry_removes_meta_inf_and_replaces_exact_entry(self):
        with tempfile.TemporaryDirectory() as td:
            apk = Path(td) / "in.apk"
            repl = Path(td) / "new.dat"
            out = Path(td) / "out.apk"
            repl.write_bytes(b"NEW")
            with zipfile.ZipFile(apk, "w") as z:
                z.writestr("META-INF/CERT.RSA", b"sig")
                z.writestr("assets/bin/huazai.dat", b"OLD")
                z.writestr("assets/index.html", b"<html>")
            info = tool.apk_replace_entry(apk, "assets/bin/huazai.dat", repl, out)
            self.assertTrue(info["removed_meta_inf"])
            with zipfile.ZipFile(out) as z:
                self.assertNotIn("META-INF/CERT.RSA", z.namelist())
                self.assertEqual(z.read("assets/bin/huazai.dat"), b"NEW")
                self.assertEqual(z.read("assets/index.html"), b"<html>")

    def test_scan_overlay_keywords_classifies_status_overlay_and_mem_injection(self):
        text = "SYSTEM_ALERT_WINDOW WindowManager TextView addView /proc/%d/mem pwrite libUE4.so"
        result = tool.classify_text(text)
        self.assertIn("java_status_overlay", result["signals"])
        self.assertIn("proc_mem_injection", result["signals"])
        self.assertNotIn("driver_chain", result["signals"])

if __name__ == "__main__":
    unittest.main()
