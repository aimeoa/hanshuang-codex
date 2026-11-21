#!/usr/bin/env python3
"""
Static companion for the "linker" style Android AArch64 shell observed in
extracted_ref/2429313026.

The reference dynamic dumper finds the real anonymous rwxp image from
/proc/<pid>/maps.  This script follows the same idea statically:

1. locate the fake high-address PT_LOAD that maps file offset 0;
2. translate e_entry through that fake mapping to the real file-entry stub;
3. disassemble the stub and recover its XOR ranges from literal loads;
4. apply the runtime XOR decryption to normal PT_LOAD-backed file ranges;
5. carve embedded ELF candidates from the reconstructed runtime image.

It deliberately does not trust section names or a fixed file offset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


PT_LOAD = 1
EM_AARCH64 = 0xB7


@dataclass
class Phdr:
    index: int
    p_type: int
    p_flags: int
    p_offset: int
    p_vaddr: int
    p_paddr: int
    p_filesz: int
    p_memsz: int
    p_align: int

    @property
    def is_load(self) -> bool:
        return self.p_type == PT_LOAD

    @property
    def file_end(self) -> int:
        return self.p_offset + self.p_filesz

    @property
    def vaddr_end(self) -> int:
        return self.p_vaddr + self.p_memsz


@dataclass
class XorRange:
    call_va: int
    target_va: int
    target_off: int
    size: int
    key: int


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_elf64(data: bytes) -> Tuple[dict, List[Phdr]]:
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise ValueError("only little-endian ELF64 is supported")
    hdr_tuple = struct.unpack("<16sHHIQQQIHHHHHH", data[:64])
    (
        e_ident,
        e_type,
        e_machine,
        e_version,
        e_entry,
        e_phoff,
        e_shoff,
        e_flags,
        e_ehsize,
        e_phentsize,
        e_phnum,
        e_shentsize,
        e_shnum,
        e_shstrndx,
    ) = hdr_tuple
    hdr = {
        "e_type": e_type,
        "e_machine": e_machine,
        "e_entry": e_entry,
        "e_phoff": e_phoff,
        "e_shoff": e_shoff,
        "e_flags": e_flags,
        "e_ehsize": e_ehsize,
        "e_phentsize": e_phentsize,
        "e_phnum": e_phnum,
        "e_shentsize": e_shentsize,
        "e_shnum": e_shnum,
        "e_shstrndx": e_shstrndx,
    }
    if e_machine != EM_AARCH64:
        raise ValueError(f"expected AArch64 ELF, got e_machine=0x{e_machine:x}")
    if e_phentsize != 56:
        raise ValueError(f"unexpected e_phentsize={e_phentsize}")
    phdrs: List[Phdr] = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if off + 56 > len(data):
            raise ValueError(f"PHDR[{i}] exceeds EOF")
        fields = struct.unpack("<IIQQQQQQ", data[off : off + 56])
        phdrs.append(Phdr(i, *fields))
    return hdr, phdrs


def find_linker_fake_load(phdrs: Iterable[Phdr], file_size: int, entry: int) -> Optional[Phdr]:
    candidates = []
    for ph in phdrs:
        if not ph.is_load:
            continue
        entry_maps_to_file = ph.p_vaddr <= entry < ph.p_vaddr + ph.p_filesz
        looks_fake = (
            ph.p_offset == 0
            and ph.p_filesz > file_size
            and (ph.p_vaddr >= 0xFFFF0000 or ph.p_filesz >= 0x10000000)
        )
        if looks_fake and entry_maps_to_file:
            candidates.append(ph)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.p_filesz)


def va_to_file(phdrs: Iterable[Phdr], va: int, file_size: int, *, allow_fake: bool) -> Optional[int]:
    best: Optional[Tuple[int, Phdr]] = None
    for ph in phdrs:
        if not ph.is_load:
            continue
        is_fake = ph.p_offset == 0 and ph.p_filesz > file_size
        if is_fake and not allow_fake:
            continue
        if ph.p_vaddr <= va < ph.p_vaddr + ph.p_filesz:
            off = ph.p_offset + (va - ph.p_vaddr)
            if off < file_size:
                span = ph.p_filesz
                if best is None or span < best[0]:
                    best = (span, ph)
    if best is None:
        return None
    ph = best[1]
    return ph.p_offset + (va - ph.p_vaddr)


def qword_at_va(data: bytes, phdrs: List[Phdr], va: int) -> int:
    off = va_to_file(phdrs, va, len(data), allow_fake=True)
    if off is None or off + 8 > len(data):
        raise ValueError(f"cannot map literal VA 0x{va:x}")
    return struct.unpack("<Q", data[off : off + 8])[0]


def recover_xor_ranges(data: bytes, phdrs: List[Phdr], entry: int, entry_off: int) -> List[XorRange]:
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
        from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_REG
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("capstone is required for stub recovery") from exc

    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    window = data[entry_off : min(len(data), entry_off + 0x400)]
    insns = list(md.disasm(window, entry))
    if not insns:
        raise ValueError("failed to disassemble true entry stub")

    last_key: Optional[int] = None
    literal_loads: Dict[str, int] = {}
    ranges: List[XorRange] = []

    for insn in insns:
        if insn.mnemonic == "mov" and len(insn.operands) == 2:
            dst, src = insn.operands
            dst_name = insn.reg_name(dst.reg) if dst.type == ARM64_OP_REG else ""
            if dst_name in ("w3", "x3") and src.type == ARM64_OP_IMM:
                last_key = src.imm & 0xFF

        if insn.mnemonic == "ldr" and len(insn.operands) == 2:
            dst, src = insn.operands
            dst_name = insn.reg_name(dst.reg) if dst.type == ARM64_OP_REG else ""
            if dst_name in ("x1", "x2") and src.type == ARM64_OP_IMM:
                literal_loads[dst_name] = qword_at_va(data, phdrs, src.imm)

        if insn.mnemonic == "bl":
            if last_key is None or "x1" not in literal_loads or "x2" not in literal_loads:
                continue
            target_va = literal_loads["x2"]
            size = literal_loads["x1"]
            target_off = va_to_file(phdrs, target_va, len(data), allow_fake=False)
            if target_off is None:
                continue
            if size <= 0 or target_off >= len(data):
                continue
            ranges.append(
                XorRange(
                    call_va=insn.address,
                    target_va=target_va,
                    target_off=target_off,
                    size=min(size, len(data) - target_off),
                    key=last_key,
                )
            )

        # The current shell returns after cache flush.  Stop before data/hex blob.
        if insn.mnemonic == "ret" and insn.address > entry:
            break

    # Deduplicate by target+size, preserving call order.
    seen = set()
    out: List[XorRange] = []
    for item in ranges:
        key = (item.target_va, item.target_off, item.size, item.key)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def apply_xor_ranges(data: bytes, ranges: Iterable[XorRange]) -> bytearray:
    out = bytearray(data)
    for r in ranges:
        end = min(r.target_off + r.size, len(out))
        for i in range(r.target_off, end):
            out[i] ^= r.key
    return out


def strings(data: bytes, min_len: int = 4) -> List[Tuple[int, str]]:
    return [(m.start(), m.group().decode("latin1", "replace")) for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data)]


def carve_embedded_elfs(data: bytes, out_dir: Path) -> List[dict]:
    elf_offsets = [m.start() for m in re.finditer(re.escape(b"\x7fELF"), data)]
    carved = []
    for n, off in enumerate(elf_offsets):
        if off == 0:
            continue
        next_off = next((x for x in elf_offsets if x > off), len(data))
        blob = data[off:next_off]
        if len(blob) < 64:
            continue
        info = {
            "offset": off,
            "size_to_next_elf_or_eof": len(blob),
            "sha256": sha256(blob),
            "path": str(out_dir / f"embedded_{off:x}_to_next.bin"),
            "elf_header_ok": False,
            "upx_strings": [],
        }
        try:
            hdr, phdrs = parse_elf64(blob)
            info["elf_header_ok"] = True
            info["elf"] = hdr
            info["program_headers"] = [asdict(p) for p in phdrs]
            max_load_end = max((p.file_end for p in phdrs if p.is_load), default=0)
            info["max_load_file_end"] = max_load_end
            info["sectionless"] = hdr["e_shoff"] == 0 or hdr["e_shnum"] == 0
        except Exception as exc:
            info["parse_error"] = str(exc)
        for pat in (b"UPX!", b"$Info: This file is packed with the UPX", b"$Id: UPX"):
            pos = blob.find(pat)
            if pos >= 0:
                info["upx_strings"].append({"pattern": pat.decode("latin1"), "relative_offset": pos})
        Path(info["path"]).write_bytes(blob)
        carved.append(info)
    return carved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="packed/linker-style ELF")
    ap.add_argument("--out-dir", required=True, help="output directory")
    args = ap.parse_args()

    inp = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = inp.read_bytes()
    hdr, phdrs = parse_elf64(data)
    fake = find_linker_fake_load(phdrs, len(data), hdr["e_entry"])
    if fake is None:
        raise SystemExit("linker fake PT_LOAD not found; refusing to hardcode offsets")

    true_entry_off = hdr["e_entry"] - fake.p_vaddr + fake.p_offset
    if not (0 <= true_entry_off < len(data)):
        raise SystemExit(f"true entry offset 0x{true_entry_off:x} outside file")

    xor_ranges = recover_xor_ranges(data, phdrs, hdr["e_entry"], true_entry_off)
    if not xor_ranges:
        raise SystemExit("no XOR ranges recovered from true entry stub")

    runtime = apply_xor_ranges(data, xor_ranges)
    runtime_path = out_dir / f"{inp.name}.linker_xor_runtime.bin"
    runtime_path.write_bytes(runtime)

    carved_dir = out_dir / "embedded_elfs"
    carved_dir.mkdir(exist_ok=True)
    carved = carve_embedded_elfs(bytes(runtime), carved_dir)

    ss = strings(bytes(runtime))
    interesting = []
    rx = re.compile(r"(ELF-Box|Nanxee|rc4|UPX|/proc/self/exe|/proc/self/maps|/system/bin/sh|xiaocaiye)", re.I)
    for off, s in ss:
        if rx.search(s):
            interesting.append({"offset": off, "string": s[:240]})

    report = {
        "input": str(inp),
        "input_size": len(data),
        "input_sha256": sha256(data),
        "runtime_image": str(runtime_path),
        "runtime_sha256": sha256(bytes(runtime)),
        "elf": hdr,
        "fake_linker_load": asdict(fake),
        "true_file_entry_offset": true_entry_off,
        "xor_ranges": [asdict(x) for x in xor_ranges],
        "embedded_elfs": carved,
        "interesting_runtime_strings": interesting[:200],
    }
    report_path = out_dir / "linker_static_unwrap_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
