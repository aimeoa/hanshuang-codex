#!/usr/bin/env python3
"""Evidence-bound AArch64 Hikari/OLLVM indirect-dispatch rewriter.

This provider intentionally handles only two closed forms:
  * relocation/raw-qword backed LDR + BR/BLR
  * two-entry CMP/CSET/table-LDR/BR selectors

Everything else is reported as unresolved rather than guessed.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs
    from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
except ImportError as exc:  # pragma: no cover - exercised by environment gate
    raise SystemExit("capstone is required: python -m pip install capstone") from exc


EM_AARCH64 = 183
PT_LOAD = 1
PF_X = 1
SHT_NOBITS = 8
R_AARCH64_RELATIVE = 0x403
COND_CODES = {
    "eq": 0x0, "ne": 0x1, "cs": 0x2, "hs": 0x2,
    "cc": 0x3, "lo": 0x3, "mi": 0x4, "pl": 0x5,
    "vs": 0x6, "vc": 0x7, "hi": 0x8, "ls": 0x9,
    "ge": 0xA, "lt": 0xB, "gt": 0xC, "le": 0xD,
}
MBA_MNEMONICS = {
    "add", "adds", "sub", "subs", "neg", "negs", "and", "ands",
    "orr", "eor", "eon", "bic", "bics", "mvn", "lsl", "lsr",
    "asr", "ror", "ubfx", "sbfx", "bfi", "bfxil", "extr", "csel",
    "csinc", "csinv", "csneg", "cset", "csetm", "madd", "msub", "mul",
}


@dataclass(frozen=True)
class Segment:
    index: int
    flags: int
    offset: int
    vaddr: int
    filesz: int
    memsz: int
    align: int


@dataclass(frozen=True)
class Section:
    index: int
    name: str
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int
    entsize: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def in_bounds(data: bytes, offset: int, size: int) -> bool:
    return 0 <= offset <= len(data) and 0 <= size <= len(data) - offset


class Elf64AArch64:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.data = path.read_bytes()
        if self.data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("input must be ELF64 little-endian")
        if len(self.data) < 64:
            raise ValueError("truncated ELF header")
        self.machine = struct.unpack_from("<H", self.data, 18)[0]
        if self.machine != EM_AARCH64:
            raise ValueError(f"expected EM_AARCH64 ({EM_AARCH64}), got {self.machine}")
        self.elf_type = struct.unpack_from("<H", self.data, 16)[0]
        self.entry = struct.unpack_from("<Q", self.data, 24)[0]
        phoff = struct.unpack_from("<Q", self.data, 32)[0]
        shoff = struct.unpack_from("<Q", self.data, 40)[0]
        phentsize, phnum = struct.unpack_from("<HH", self.data, 54)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", self.data, 58)
        self.program_header_end = phoff + phentsize * phnum if phnum else 64
        self.section_header_end = shoff + shentsize * shnum if shoff and shnum else 0
        self.max_program_file_end = 0

        self.segments: list[Segment] = []
        if phnum and phentsize < 56:
            raise ValueError("invalid ELF64 program-header entry size")
        for index in range(phnum):
            offset = phoff + index * phentsize
            if not in_bounds(self.data, offset, 56):
                raise ValueError("program-header table is truncated")
            values = struct.unpack_from("<IIQQQQQQ", self.data, offset)
            if values[5] and in_bounds(self.data, values[2], values[5]):
                self.max_program_file_end = max(self.max_program_file_end, values[2] + values[5])
            if values[0] == PT_LOAD:
                self.segments.append(Segment(
                    index=index, flags=values[1], offset=values[2],
                    vaddr=values[3], filesz=values[5], memsz=values[6],
                    align=values[7],
                ))

        self.sections: list[Section] = []
        self.section_by_name: dict[str, Section] = {}
        self.max_section_file_end = 0
        if shoff and shnum and shentsize >= 64 and shstrndx < shnum:
            raw: list[tuple[int, ...]] = []
            for index in range(shnum):
                offset = shoff + index * shentsize
                if not in_bounds(self.data, offset, 64):
                    raw = []
                    break
                raw.append(struct.unpack_from("<IIQQQQIIQQ", self.data, offset))
            if raw:
                shstr = raw[shstrndx]
                names = (
                    self.data[shstr[4]:shstr[4] + shstr[5]]
                    if in_bounds(self.data, shstr[4], shstr[5]) else b""
                )

                def get_name(name_offset: int) -> str:
                    if name_offset >= len(names):
                        return ""
                    end = names.find(b"\0", name_offset)
                    if end < 0:
                        end = len(names)
                    return names[name_offset:end].decode("utf-8", errors="replace")

                for index, values in enumerate(raw):
                    section = Section(
                        index=index, name=get_name(values[0]), sh_type=values[1],
                        flags=values[2], addr=values[3], offset=values[4],
                        size=values[5], entsize=values[9],
                    )
                    self.sections.append(section)
                    if section.sh_type != SHT_NOBITS and in_bounds(self.data, section.offset, section.size):
                        self.max_section_file_end = max(
                            self.max_section_file_end, section.offset + section.size,
                        )
                    if section.name:
                        self.section_by_name[section.name] = section

        self.relocations: dict[int, tuple[int, int]] = {}
        for name in (".rela.dyn", ".rela.plt"):
            section = self.section_by_name.get(name)
            if not section or not in_bounds(self.data, section.offset, section.size):
                continue
            entsize = section.entsize or 24
            if entsize < 24:
                continue
            for offset in range(section.offset, section.offset + section.size, entsize):
                if not in_bounds(self.data, offset, 24):
                    break
                address, info, addend = struct.unpack_from("<QQq", self.data, offset)
                self.relocations[address] = (info & 0xFFFFFFFF, addend)

    def va_to_offset(self, va: int, size: int = 1) -> int | None:
        for segment in self.segments:
            if segment.vaddr <= va and va + size <= segment.vaddr + segment.filesz:
                return segment.offset + va - segment.vaddr
        return None

    def read_va(self, va: int, size: int) -> bytes | None:
        offset = self.va_to_offset(va, size)
        return None if offset is None else self.data[offset:offset + size]

    def is_executable(self, va: int) -> bool:
        return any(
            segment.flags & PF_X and segment.vaddr <= va < segment.vaddr + segment.filesz
            for segment in self.segments
        )

    def qword_target(self, slot_va: int) -> tuple[int | None, str]:
        relocation = self.relocations.get(slot_va)
        if relocation and relocation[0] == R_AARCH64_RELATIVE:
            return relocation[1], "R_AARCH64_RELATIVE"
        raw = self.read_va(slot_va, 8)
        if raw is None:
            return None, "unmapped"
        return struct.unpack_from("<Q", raw)[0], "raw-qword"

    def executable_ranges(self) -> list[tuple[int, int]]:
        return [
            (segment.vaddr, segment.vaddr + segment.filesz)
            for segment in self.segments if segment.flags & PF_X and segment.filesz
        ]


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = collections.Counter(data)
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def comment_strings(elf: Elf64AArch64) -> list[str]:
    section = elf.section_by_name.get(".comment")
    if not section or not in_bounds(elf.data, section.offset, section.size):
        return []
    raw = elf.data[section.offset:section.offset + section.size]
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def parse_ida_functions(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    result: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            start_text = row.get("start") or row.get("addr") or row.get("address")
            if not start_text:
                continue
            start = int(start_text, 0 if str(start_text).lower().startswith("0x") else 16)
            size_text = row.get("size") or "0"
            size = int(size_text, 0 if str(size_text).lower().startswith("0x") else 16)
            result.append({
                "start": start,
                "size": size,
                "name": row.get("name") or row.get("annotated_name") or f"sub_{start:X}",
                "blocks": int(row.get("blocks") or row.get("basic_blocks") or 0),
                "instructions": int(row.get("instructions") or 0),
            })
    return sorted(result, key=lambda item: int(item["start"]))


def parse_perf_offsets(path: Path | None) -> collections.Counter[int]:
    result: collections.Counter[int] = collections.Counter()
    if path is None or not path.exists():
        return result
    patterns = [
        re.compile(r"\bvaddr_in_file:\s*([0-9a-fA-F]+)"),
        re.compile(r"\boffset[:=]\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)"),
    ]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                result[int(match.group(1), 16)] += 1
                break
    return result


def reg_number(name: str) -> int | None:
    match = re.fullmatch(r"[xw](\d+)", name.lower())
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 30 else None


def encode_b(address: int, target: int, link: bool = False) -> bytes:
    delta = target - address
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError("B/BL target out of range")
    return struct.pack("<I", (0x94000000 if link else 0x14000000) | ((delta >> 2) & 0x03FFFFFF))


def encode_b_cond(address: int, target: int, condition: str) -> bytes:
    delta = target - address
    if condition not in COND_CODES or delta % 4 or not -(1 << 20) <= delta < (1 << 20):
        raise ValueError("conditional branch target out of range")
    return struct.pack("<I", 0x54000000 | (((delta >> 2) & 0x7FFFF) << 5) | COND_CODES[condition])


def encode_adr(address: int, target: int, register: int) -> bytes:
    delta = target - address
    if not -(1 << 20) <= delta < (1 << 20):
        raise ValueError("ADR target out of range")
    immediate = delta & 0x1FFFFF
    return struct.pack(
        "<I", 0x10000000 | ((immediate & 3) << 29)
        | (((immediate >> 2) & 0x7FFFF) << 5) | register,
    )


def insn_row(insn) -> dict[str, object]:
    return {
        "address": insn.address,
        "mnemonic": insn.mnemonic.lower(),
        "op_str": insn.op_str,
        "bytes": bytes(insn.bytes),
        "object": insn,
    }


def resolve_constant_register(rows: list[dict[str, object]], target_reg_id: int) -> int | None:
    values: dict[int, int] = {}
    for row in rows:
        insn = row["object"]
        mnemonic = str(row["mnemonic"])
        before = dict(values)
        try:
            _, written = insn.regs_access()
        except Exception:
            written = []
        for reg_id in written:
            number = reg_number(insn.reg_name(reg_id))
            if number is not None:
                values.pop(number, None)
        operands = insn.operands
        if mnemonic in {"adr", "adrp"} and len(operands) >= 2:
            if operands[0].type == ARM64_OP_REG and operands[1].type == ARM64_OP_IMM:
                dst = reg_number(insn.reg_name(operands[0].reg))
                if dst is not None:
                    values[dst] = int(operands[1].imm)
        elif mnemonic == "add" and len(operands) >= 3:
            if operands[0].type == ARM64_OP_REG and operands[1].type == ARM64_OP_REG and operands[2].type == ARM64_OP_IMM:
                dst = reg_number(insn.reg_name(operands[0].reg))
                src = reg_number(insn.reg_name(operands[1].reg))
                if dst is not None and src in before:
                    values[dst] = before[src] + int(operands[2].imm)
        elif mnemonic == "mov" and len(operands) >= 2:
            if operands[0].type == ARM64_OP_REG and operands[1].type == ARM64_OP_REG:
                dst = reg_number(insn.reg_name(operands[0].reg))
                src = reg_number(insn.reg_name(operands[1].reg))
                if dst is not None and src in before:
                    values[dst] = before[src]
    target = reg_number(rows[-1]["object"].reg_name(target_reg_id)) if rows else None
    return values.get(target) if target is not None else None


def patch_record(kind: str, va: int, file_offset: int, old: bytes, new: bytes, **detail) -> dict[str, object]:
    if len(old) != len(new):
        raise ValueError("patch length changed")
    return {
        "kind": kind, "va": hex(va), "file_offset": hex(file_offset),
        "size": len(old), "old_bytes": old.hex(), "new_bytes": new.hex(),
        **detail,
    }


def inspect_elf(elf: Elf64AArch64) -> dict[str, object]:
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    counts: collections.Counter[str] = collections.Counter()
    decoded = 0
    text = elf.section_by_name.get(".text")
    ranges = [(text.addr, text.addr + text.size)] if text and text.size else elf.executable_ranges()
    for start, end in ranges:
        raw = elf.read_va(start, end - start)
        if raw is None:
            continue
        for insn in md.disasm(raw, start):
            decoded += 1
            counts[insn.mnemonic.lower()] += 1
    comments = comment_strings(elf)
    hikari_comments = [value for value in comments if "hikari" in value.lower()]
    mapped_end = max((segment.offset + segment.filesz for segment in elf.segments), default=0)
    represented_end = max(
        64,
        elf.program_header_end if elf.program_header_end <= len(elf.data) else 0,
        elf.section_header_end if elf.section_header_end <= len(elf.data) else 0,
        elf.max_program_file_end,
        elf.max_section_file_end,
    )
    relative_code = sum(
        kind == R_AARCH64_RELATIVE and elf.is_executable(addend)
        for kind, addend in elf.relocations.values()
    )
    return {
        "schema": "xigong.funk-hikari.triage/v1",
        "root": {
            "path": str(elf.path), "size": len(elf.data),
            "sha256": sha256_bytes(elf.data), "elf_type": elf.elf_type,
            "machine": elf.machine, "entry": hex(elf.entry),
        },
        "layout": {
            "load_segments": [segment.__dict__ for segment in elf.segments],
            "sections": len(elf.sections),
            "mapped_file_end": hex(mapped_end),
            "represented_file_end": hex(represented_end),
            "post_load_tail_size": max(0, len(elf.data) - mapped_end),
            "overlay_offset": hex(represented_end),
            "overlay_size": max(0, len(elf.data) - represented_end),
            "file_entropy": round(entropy(elf.data), 6),
        },
        "provenance": {
            "comments": comments,
            "hikari_comments": hikari_comments,
            "hikari_level": "E3_PROVEN_PROVENANCE" if hikari_comments else "UNKNOWN",
        },
        "morphology": {
            "decoded_instructions": decoded,
            "br": counts["br"], "blr": counts["blr"],
            "conditional": sum(counts[f"b.{cond}"] for cond in set(COND_CODES)),
            "mba_instructions": sum(counts[name] for name in MBA_MNEMONICS),
            "relative_relocations": sum(kind == R_AARCH64_RELATIVE for kind, _ in elf.relocations.values()),
            "relative_code_targets": relative_code,
            "claims": [
                "family provenance and individual pass recovery remain separate",
                "CFF/VM are not proven by BR/BLR, entropy, MBA density, or markers alone",
            ],
        },
    }


def analyze(elf: Elf64AArch64, functions: list[dict[str, object]], perf: collections.Counter[int], max_fragment: int) -> dict[str, object]:
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    relocation_targets = sorted({
        addend for kind, addend in elf.relocations.values()
        if kind == R_AARCH64_RELATIVE and addend % 4 == 0 and elf.is_executable(addend)
    })
    starts = {elf.entry, *relocation_targets, *(int(item["start"]) for item in functions)}
    starts = sorted(start for start in starts if elf.is_executable(start))
    patches: list[dict[str, object]] = []
    occupied: list[tuple[int, int]] = []
    static_sites: list[dict[str, object]] = []
    selector_sites: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    stats: collections.Counter[str] = collections.Counter()

    def admit(record: dict[str, object]) -> bool:
        begin = int(str(record["file_offset"]), 16)
        end = begin + int(record["size"])
        if any(begin < old_end and old_begin < end for old_begin, old_end in occupied):
            return False
        occupied.append((begin, end))
        patches.append(record)
        return True

    for index, start in enumerate(starts):
        containing_end = next((end for begin, end in elf.executable_ranges() if begin <= start < end), start)
        next_start = starts[index + 1] if index + 1 < len(starts) else containing_end
        end = min(containing_end, next_start, start + max_fragment)
        if end <= start:
            continue
        raw = elf.read_va(start, end - start)
        if not raw:
            continue
        rows = [insn_row(insn) for insn in md.disasm(raw, start)]
        if not rows:
            continue
        stats["fragments"] += 1
        stats["instructions"] += len(rows)
        stats["mba_instructions"] += sum(str(row["mnemonic"]) in MBA_MNEMONICS for row in rows)
        mnemonics = [str(row["mnemonic"]) for row in rows]

        # Closed form 1: last target definition is LDR, terminal BR/BLR uses it.
        if len(rows) >= 3 and mnemonics[-1] in {"br", "blr"}:
            terminal = rows[-1]["object"]
            branch_reg = terminal.operands[0].reg if terminal.operands and terminal.operands[0].type == ARM64_OP_REG else None
            branch_number = reg_number(terminal.reg_name(branch_reg)) if branch_reg is not None else None
            load_index: int | None = None
            if branch_number is not None:
                for candidate_index in range(len(rows) - 2, max(-1, len(rows) - 12), -1):
                    candidate = rows[candidate_index]["object"]
                    if not candidate.operands or candidate.operands[0].type != ARM64_OP_REG:
                        continue
                    if reg_number(candidate.reg_name(candidate.operands[0].reg)) != branch_number:
                        continue
                    if candidate.mnemonic.lower() == "ldr":
                        load_index = candidate_index
                    break
            if load_index is not None:
                load = rows[load_index]["object"]
                if len(load.operands) >= 2 and load.operands[1].type == ARM64_OP_MEM and load.operands[1].mem.index == 0:
                    base = resolve_constant_register(rows[:load_index], load.operands[1].mem.base)
                    if base is not None:
                        slot = base + int(load.operands[1].mem.disp)
                        target, provenance = elf.qword_target(slot)
                        if target is not None and elf.is_executable(target):
                            load_va = int(rows[load_index]["address"])
                            branch_va = int(rows[-1]["address"])
                            try:
                                old = b"".join(bytes(row["bytes"]) for row in rows[load_index:])
                                middle = b"".join(bytes(row["bytes"]) for row in rows[load_index + 1:-1])
                                new = encode_adr(load_va, target, branch_number) + middle + encode_b(
                                    branch_va, target, link=mnemonics[-1] == "blr",
                                )
                                file_offset = elf.va_to_offset(load_va, len(old))
                                if file_offset is not None and old != new:
                                    record = patch_record(
                                        "static-indirect-call" if mnemonics[-1] == "blr" else "static-indirect-branch",
                                        load_va, file_offset, old, new,
                                        slot_va=hex(slot), target_va=hex(target),
                                        target_register=terminal.reg_name(branch_reg), provenance=provenance,
                                        semantic="preserve target-register value and BR/BLR control target using ADR+B/BL",
                                        proof=["same target register", "closed pointer slot", "target in executable PT_LOAD"],
                                    )
                                    if admit(record):
                                        static_sites.append(record)
                            except ValueError as exc:
                                unresolved.append({
                                    "va": hex(branch_va), "fragment_start": hex(start),
                                    "reason": str(exc), "kind": "static-target-encoding",
                                })

        # Closed form 2: exact six-instruction two-entry selector tail.
        if len(rows) >= 6:
            tail = rows[-6:]
            tail_names = [str(row["mnemonic"]) for row in tail]
            if tail_names == ["cmp", "adrp", "add", "cset", "ldr", "br"]:
                cset, load, branch = tail[3]["object"], tail[4]["object"], tail[5]["object"]
                if (
                    cset.operands and cset.operands[0].type == ARM64_OP_REG
                    and len(load.operands) >= 2 and load.operands[0].type == ARM64_OP_REG
                    and load.operands[1].type == ARM64_OP_MEM
                    and branch.operands and branch.operands[0].type == ARM64_OP_REG
                    and load.operands[0].reg == branch.operands[0].reg
                    and load.operands[1].mem.index == cset.operands[0].reg
                ):
                    base = resolve_constant_register(tail[1:3], load.operands[1].mem.base)
                    condition = str(tail[3]["op_str"]).split(",")[-1].strip().lower()
                    target_reg = reg_number(load.reg_name(load.operands[0].reg))
                    if base is not None and condition in COND_CODES and target_reg is not None:
                        false_target, p0 = elf.qword_target(base)
                        true_target, p1 = elf.qword_target(base + 8)
                        if false_target is not None and true_target is not None and elf.is_executable(false_target) and elf.is_executable(true_target):
                            cmp_va = int(tail[0]["address"])
                            try:
                                old = b"".join(bytes(row["bytes"]) for row in tail)
                                new = b"".join([
                                    bytes(tail[0]["bytes"]),
                                    encode_b_cond(cmp_va + 4, cmp_va + 16, condition),
                                    encode_adr(cmp_va + 8, false_target, target_reg),
                                    encode_b(cmp_va + 12, false_target),
                                    encode_adr(cmp_va + 16, true_target, target_reg),
                                    encode_b(cmp_va + 20, true_target),
                                ])
                                file_offset = elf.va_to_offset(cmp_va, len(old))
                                if file_offset is not None and old != new:
                                    record = patch_record(
                                        "two-entry-selector", cmp_va, file_offset, old, new,
                                        table_va=hex(base), false_target_va=hex(false_target),
                                        true_target_va=hex(true_target), condition=condition,
                                        target_register=load.reg_name(load.operands[0].reg),
                                        provenance=[p0, p1],
                                        semantic="preserve CMP/CSET condition and target-register value; replace two-entry table dispatch with direct edges",
                                        proof=["CSET index is 0/1", "both table entries executable", "same terminal target register"],
                                    )
                                    if admit(record):
                                        selector_sites.append(record)
                            except ValueError as exc:
                                unresolved.append({
                                    "va": hex(cmp_va), "fragment_start": hex(start),
                                    "reason": str(exc), "kind": "selector-target-encoding",
                                })

        for row in rows:
            if row["mnemonic"] not in {"br", "blr"}:
                continue
            address = int(row["address"])
            if any(int(str(patch["va"]), 16) <= address < int(str(patch["va"]), 16) + int(patch["size"]) for patch in patches):
                continue
            unresolved.append({
                "va": hex(address), "fragment_start": hex(start),
                "mnemonic": row["mnemonic"], "op_str": row["op_str"],
                "runtime_hits": perf.get(address, 0),
                "reason": "target is not closed by a supported local contract",
            })

    return {
        "starts": starts, "relocation_targets": relocation_targets,
        "patches": sorted(patches, key=lambda item: int(str(item["file_offset"]), 16)),
        "static_sites": static_sites, "selector_sites": selector_sites,
        "unresolved": unresolved, "stats": dict(stats),
    }


def apply_patches(root: bytes, patches: Iterable[dict[str, object]]) -> bytes:
    output = bytearray(root)
    occupied: list[tuple[int, int]] = []
    for patch in patches:
        offset = int(str(patch["file_offset"]), 16)
        old = bytes.fromhex(str(patch["old_bytes"]))
        new = bytes.fromhex(str(patch["new_bytes"]))
        end = offset + len(old)
        if any(offset < prior_end and prior_start < end for prior_start, prior_end in occupied):
            raise ValueError(f"overlapping patch at {offset:#x}")
        if bytes(output[offset:end]) != old:
            raise ValueError(f"expected bytes mismatch at {offset:#x}")
        output[offset:end] = new
        occupied.append((offset, end))
    return bytes(output)


def verify(root: bytes, output: bytes, patches: list[dict[str, object]]) -> dict[str, object]:
    allowed: set[int] = set()
    for patch in patches:
        offset = int(str(patch["file_offset"]), 16)
        allowed.update(range(offset, offset + int(patch["size"])))
    diffs = [index for index, (before, after) in enumerate(zip(root, output)) if before != after]
    unexpected = [index for index in diffs if index not in allowed]
    rollback = bytearray(output)
    for patch in patches:
        offset = int(str(patch["file_offset"]), 16)
        old = bytes.fromhex(str(patch["old_bytes"]))
        rollback[offset:offset + len(old)] = old
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    decoded = 0
    for patch in patches:
        new = bytes.fromhex(str(patch["new_bytes"]))
        va = int(str(patch["va"]), 16)
        if sum(insn.size for insn in md.disasm(new, va)) == len(new):
            decoded += 1
    return {
        "size_equal": len(root) == len(output),
        "diff_byte_count": len(diffs),
        "unexpected_diff_count": len(unexpected),
        "patch_ranges_disassembled": decoded,
        "all_patch_ranges_disassemble": decoded == len(patches),
        "rollback_sha256": sha256_bytes(bytes(rollback)),
        "rollback_matches_root": bytes(rollback) == root,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--inspect", action="store_true", help="triage only; do not require an output")
    parser.add_argument("--ida-functions", type=Path)
    parser.add_argument("--perf-samples", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--max-fragment", type=lambda value: int(value, 0), default=0x400)
    parser.add_argument("--require-hikari-marker", action="store_true")
    args = parser.parse_args()

    elf = Elf64AArch64(args.input)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    triage = inspect_elf(elf)
    triage_path = args.report_dir / "triage.json"
    triage_path.write_text(json.dumps(triage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.require_hikari_marker and not triage["provenance"]["hikari_comments"]:
        raise SystemExit("Hikari provenance marker required but not found in .comment")
    if args.inspect:
        print(json.dumps(triage, ensure_ascii=False, indent=2))
        return 0
    if args.out is None:
        parser.error("--out is required unless --inspect is used")

    functions = parse_ida_functions(args.ida_functions)
    perf = parse_perf_offsets(args.perf_samples)
    result = analyze(elf, functions, perf, args.max_fragment)
    output = apply_patches(elf.data, result["patches"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    verification = verify(elf.data, output, result["patches"])
    report = {
        "schema": "xigong.funk-hikari.static-rewrite/v1",
        "triage": triage,
        "output": {
            "path": str(args.out.resolve()), "size": len(output),
            "sha256": sha256_bytes(output),
        },
        "scope": {
            "provider": "AArch64 relocation-backed indirect dispatch and exact two-entry selectors",
            "family_claim": triage["provenance"]["hikari_level"],
            "global_cff": "NOT_EVALUATED_BY_THIS_PROVIDER",
            "vm": "NOT_EVALUATED_BY_THIS_PROVIDER",
        },
        "counts": {
            "ida_functions": len(functions),
            "perf_offsets": len(perf),
            "fragment_starts": len(result["starts"]),
            "relocation_code_targets": len(result["relocation_targets"]),
            "patches": len(result["patches"]),
            "static_indirect": len(result["static_sites"]),
            "two_entry_selectors": len(result["selector_sites"]),
            "unresolved_indirect": len(result["unresolved"]),
            **result["stats"],
        },
        "verification": verification,
        "next_gate": (
            "runtime equivalence, then plaintext sufficiency gate"
            if result["patches"] else
            "provider not applicable; use pass-specific analysis or runtime materialization"
        ),
    }
    (args.report_dir / "patch_manifest.json").write_text(json.dumps({
        "schema": "xigong.funk-hikari.patch-transaction/v1",
        "root_sha256": sha256_bytes(elf.data),
        "output_sha256": sha256_bytes(output),
        "patches": result["patches"], "verification": verification,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "resolved_indirect.json").write_text(json.dumps({
        "static": result["static_sites"], "selectors": result["selector_sites"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "unresolved_indirect.json").write_text(json.dumps({
        "schema": "xigong.funk-hikari.unresolved-indirect/v1",
        "sites": result["unresolved"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "static_rewrite_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = all([
        verification["size_equal"], verification["unexpected_diff_count"] == 0,
        verification["all_patch_ranges_disassemble"], verification["rollback_matches_root"],
    ])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
