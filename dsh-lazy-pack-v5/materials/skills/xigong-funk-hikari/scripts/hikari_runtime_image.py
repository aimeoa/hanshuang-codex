#!/usr/bin/env python3
"""Capture, rebuild, search, package, and verify Hikari runtime inner images."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path


PAGE = 0x1000
PT_LOAD = 1
PF_X, PF_W, PF_R = 1, 2, 4
SHT_NULL, SHT_PROGBITS, SHT_STRTAB = 0, 1, 3
SHF_WRITE, SHF_ALLOC, SHF_EXECINSTR = 1, 2, 4
EM_AARCH64 = 183
CARRIER_MAGIC = b"XG-FUNK-HIKARI/1\0"
CARRIER_TRAILER_SIZE = PAGE
MAP_RE = re.compile(
    r"^(?P<start>[0-9a-fA-F]+)-(?P<end>[0-9a-fA-F]+)\s+"
    r"(?P<perms>[-rwxps]+)\s+(?P<offset>[0-9a-fA-F]+)\s+"
    r"\S+\s+\d+\s*(?P<name>.*)$"
)
CAPTURE_FILE_RE = re.compile(r"^(?P<start>[0-9a-fA-F]{8,16})-(?P<end>[0-9a-fA-F]{8,16})\.bin$")


def align(value: int, amount: int = PAGE) -> int:
    return (value + amount - 1) & -amount


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_int(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def parse_range(value: str) -> tuple[int, int]:
    try:
        left, right = value.split(":", 1)
        start, end = int(left, 0), int(right, 0)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"invalid range {value!r}; expected 0xSTART:0xEND") from exc
    if start >= end:
        raise argparse.ArgumentTypeError("range start must be below end")
    return start, end


@dataclass(frozen=True)
class Mapping:
    start: int
    end: int
    perms: str
    offset: int
    name: str

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class CapturedMapping:
    start: int
    end: int
    perms: str
    name: str
    source_start: int
    source_end: int
    source_path: Path
    data: bytes

    @property
    def size(self) -> int:
        return self.end - self.start


def parse_maps(text: str) -> list[Mapping]:
    result: list[Mapping] = []
    for line in text.splitlines():
        match = MAP_RE.match(line.strip())
        if not match:
            continue
        result.append(Mapping(
            start=int(match.group("start"), 16),
            end=int(match.group("end"), 16),
            perms=match.group("perms"),
            offset=int(match.group("offset"), 16),
            name=match.group("name").strip(),
        ))
    return result


def adb_run(adb: str, serial: str, *args: str, binary: bool = False, timeout: float = 60.0) -> bytes | str:
    result = subprocess.run(
        [adb, "-s", serial, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(
            f"adb failed ({result.returncode}): {result.stderr.decode('utf-8', errors='replace')}"
        )
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def adb_su(adb: str, serial: str, command: str, binary: bool = False, timeout: float = 60.0) -> bytes | str:
    return adb_run(adb, serial, "exec-out", "su", "-c", command, binary=binary, timeout=timeout)


def selected(mapping: Mapping, ranges: list[tuple[int, int]], target_name: str) -> bool:
    if "r" not in mapping.perms or mapping.size <= 0:
        return False
    if ranges and any(mapping.start < end and start < mapping.end for start, end in ranges):
        return True
    return bool(target_name and target_name in mapping.name)


def read_mapping(adb: str, serial: str, pid: int, mapping: Mapping, timeout: float) -> bytes:
    if mapping.start % PAGE or mapping.size % PAGE:
        raise ValueError(f"mapping is not page aligned: {mapping.start:#x}-{mapping.end:#x}")
    command = (
        f"dd if=/proc/{pid}/mem bs={PAGE} skip={mapping.start // PAGE} "
        f"count={mapping.size // PAGE} 2>/dev/null"
    )
    data = adb_su(adb, serial, command, binary=True, timeout=timeout)
    assert isinstance(data, bytes)
    if len(data) != mapping.size:
        raise RuntimeError(f"short read: expected {mapping.size}, got {len(data)}")
    return data


def command_capture(args: argparse.Namespace) -> int:
    if not args.range and not args.target_name:
        raise SystemExit("capture requires at least one --range or --target-name")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    maps_text = adb_su(args.adb, args.serial, f"cat /proc/{args.pid}/maps")
    cmdline_raw = adb_su(args.adb, args.serial, f"cat /proc/{args.pid}/cmdline", binary=True)
    exe_path = str(adb_su(
        args.adb, args.serial, f"readlink /proc/{args.pid}/exe 2>/dev/null || true",
    )).strip()
    exe_hash_output = str(adb_su(
        args.adb, args.serial, f"sha256sum /proc/{args.pid}/exe 2>/dev/null || true",
    )).strip()
    exe_hash_match = re.match(r"^([0-9a-fA-F]{64})(?:\s|$)", exe_hash_output)
    exe_sha256 = exe_hash_match.group(1).lower() if exe_hash_match else ""
    assert isinstance(maps_text, str) and isinstance(cmdline_raw, bytes)
    maps_bytes = maps_text.encode("utf-8")
    # Preserve the device newline bytes on Windows so the recorded hash binds
    # the actual file instead of a pre-translation text representation.
    (args.out_dir / "maps.txt").write_bytes(maps_bytes)
    mappings = [mapping for mapping in parse_maps(maps_text) if selected(mapping, args.range, args.target_name)]
    total = 0
    records: list[dict[str, object]] = []
    for mapping in mappings:
        record: dict[str, object] = {
            "start": hex(mapping.start), "end": hex(mapping.end),
            "size": mapping.size, "perms": mapping.perms,
            "offset": hex(mapping.offset), "name": mapping.name,
        }
        if mapping.size > args.max_mapping:
            record.update(status="SKIPPED_MAX_MAPPING")
            records.append(record)
            continue
        if total + mapping.size > args.max_total:
            record.update(status="SKIPPED_MAX_TOTAL")
            records.append(record)
            continue
        try:
            data = read_mapping(args.adb, args.serial, args.pid, mapping, args.timeout)
        except Exception as exc:
            record.update(status="READ_FAILED", error=str(exc))
            records.append(record)
            continue
        filename = f"{mapping.start:016x}-{mapping.end:016x}.bin"
        (args.out_dir / filename).write_bytes(data)
        record.update(status="CAPTURED", file=filename, sha256=sha256(data))
        records.append(record)
        total += len(data)
    report = {
        "schema": "xigong.funk-hikari.runtime-capture/v1",
        "captured_at_unix": time.time(), "serial": args.serial, "pid": args.pid,
        "cmdline_hex": cmdline_raw.hex(),
        "cmdline": cmdline_raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip(),
        "executable": {
            "proc_path": f"/proc/{args.pid}/exe", "resolved_path": exe_path,
            "sha256": exe_sha256, "identity_bound": bool(exe_sha256),
        },
        "selection": {
            "ranges": [[hex(start), hex(end)] for start, end in args.range],
            "target_name": args.target_name,
        },
        "maps_sha256": sha256(maps_bytes),
        "maps_encoding": "utf-8", "maps_newline": "device-preserved",
        "captured_bytes": total, "mappings": records,
    }
    report_path = args.out_dir / "capture.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(report_path.resolve()), "captured_bytes": total,
        "captured_mappings": sum(item["status"] == "CAPTURED" for item in records),
        "failed_mappings": sum(item["status"] == "READ_FAILED" for item in records),
    }, ensure_ascii=False, indent=2))
    return 0 if total else 1


def read_capture_report(capture_dir: Path) -> dict[str, object]:
    path = capture_dir / "capture.json"
    if not path.exists():
        raise ValueError(f"missing {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"capture report is not an object: {path}")
    return report


def verified_capture_records(capture_dir: Path, report: dict[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw in report.get("mappings", []):
        if not isinstance(raw, dict) or raw.get("status") != "CAPTURED" or not raw.get("file"):
            continue
        record = dict(raw)
        path = capture_dir / str(record["file"])
        if not path.exists():
            raise ValueError(f"missing captured mapping: {path}")
        actual_size, actual_sha256 = path.stat().st_size, sha256_file(path)
        if actual_size != parse_int(record["size"]):
            raise ValueError(f"captured mapping size mismatch: {path}")
        if actual_sha256 != str(record.get("sha256")):
            raise ValueError(f"captured mapping hash mismatch: {path}")
        record["verified_sha256"] = actual_sha256
        result.append(record)
    if not result:
        raise ValueError(f"no captured mappings in {capture_dir}")
    return result


def capture_record_key(record: dict[str, object]) -> tuple[object, ...]:
    return (
        parse_int(record["start"]), parse_int(record["end"]), str(record.get("perms", "")),
        parse_int(record.get("offset", 0)), str(record.get("name", "")),
    )


def verify_maps_file(capture_dir: Path, report: dict[str, object]) -> dict[str, object]:
    path = capture_dir / "maps.txt"
    if not path.exists():
        raise ValueError(f"missing {path}")
    raw = path.read_bytes()
    physical_hash = sha256(raw)
    expected = str(report.get("maps_sha256", ""))
    normalized = raw.replace(b"\r\n", b"\n")
    normalized_hash = sha256(normalized)
    mode = "exact" if physical_hash == expected else "legacy-crlf-normalized" if normalized_hash == expected else "mismatch"
    return {
        "path": str(path.resolve()), "physical_sha256": physical_hash,
        "canonical_sha256": expected, "lf_normalized_sha256": normalized_hash,
        "integrity_valid": mode != "mismatch", "match_mode": mode,
    }


def command_compare_captures(args: argparse.Namespace) -> int:
    left_report, right_report = read_capture_report(args.left), read_capture_report(args.right)
    left_maps, right_maps = verify_maps_file(args.left, left_report), verify_maps_file(args.right, right_report)
    left_records = {capture_record_key(item): item for item in verified_capture_records(args.left, left_report)}
    right_records = {capture_record_key(item): item for item in verified_capture_records(args.right, right_report)}
    keys = sorted(set(left_records) | set(right_records))
    comparisons: list[dict[str, object]] = []
    for key in keys:
        left, right = left_records.get(key), right_records.get(key)
        comparisons.append({
            "start": hex(int(key[0])), "end": hex(int(key[1])), "perms": key[2],
            "offset": hex(int(key[3])), "name": key[4],
            "left_sha256": left.get("verified_sha256") if left else None,
            "right_sha256": right.get("verified_sha256") if right else None,
            "same_bytes": bool(left and right and left["verified_sha256"] == right["verified_sha256"]),
        })
    layout_equal = set(left_records) == set(right_records)
    mapping_hashes_equal = layout_equal and all(item["same_bytes"] for item in comparisons)
    same_pid = left_report.get("pid") == right_report.get("pid") if "pid" in left_report and "pid" in right_report else None
    cmdline_equal = left_report.get("cmdline_hex") == right_report.get("cmdline_hex")
    maps_hash_equal = left_report.get("maps_sha256") == right_report.get("maps_sha256")
    left_executable = left_report.get("executable") if isinstance(left_report.get("executable"), dict) else {}
    right_executable = right_report.get("executable") if isinstance(right_report.get("executable"), dict) else {}
    left_exe_hash, right_exe_hash = str(left_executable.get("sha256", "")), str(right_executable.get("sha256", ""))
    executable_hash_equal = left_exe_hash == right_exe_hash if left_exe_hash and right_exe_hash else None
    # Unrelated mappings may legitimately churn between two reads. The selected
    # cluster, process identity, and captured bytes are the integrity contract;
    # the full maps hash remains corroborating evidence.
    passed = bool(
        left_maps["integrity_valid"] and right_maps["integrity_valid"]
        and layout_equal and mapping_hashes_equal and cmdline_equal
        and same_pid is not False and executable_hash_equal is not False
    )
    report = {
        "schema": "xigong.funk-hikari.capture-comparison/v1",
        "left": str(args.left.resolve()), "right": str(args.right.resolve()),
        "same_pid": same_pid, "cmdline_equal": cmdline_equal,
        "left_executable": left_executable, "right_executable": right_executable,
        "executable_sha256_equal": executable_hash_equal,
        "maps_sha256_equal": maps_hash_equal, "layout_equal": layout_equal,
        "left_maps": left_maps, "right_maps": right_maps,
        "all_mapping_hashes_equal": mapping_hashes_equal,
        "capture_integrity_equal": passed, "mappings": comparisons,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def load_capture(capture_dir: Path, base: int, end: int) -> list[CapturedMapping]:
    report = read_capture_report(capture_dir)
    result: list[CapturedMapping] = []
    for record in report.get("mappings", []):
        if record.get("status") != "CAPTURED" or not record.get("file"):
            continue
        path = capture_dir / str(record["file"])
        match = CAPTURE_FILE_RE.fullmatch(path.name)
        if not match or not path.exists():
            continue
        source_start, source_end = int(match.group("start"), 16), int(match.group("end"), 16)
        data = path.read_bytes()
        if len(data) != source_end - source_start:
            raise ValueError(f"captured file size mismatch: {path}")
        if sha256(data) != str(record.get("sha256")):
            raise ValueError(f"captured file hash mismatch: {path}")
        clipped_start, clipped_end = max(base, source_start), min(end, source_end)
        if clipped_start >= clipped_end:
            continue
        left, right = clipped_start - source_start, clipped_end - source_start
        result.append(CapturedMapping(
            start=clipped_start, end=clipped_end, perms=str(record["perms"]),
            name=str(record.get("name", "")), source_start=source_start,
            source_end=source_end, source_path=path.resolve(), data=data[left:right],
        ))
    result.sort(key=lambda item: item.start)
    if not result:
        raise ValueError("no captured mappings overlap requested range")
    for prior, current in zip(result, result[1:]):
        if current.start < prior.end:
            raise ValueError("captured mappings overlap after clipping")
    return result


def permission_flags(perms: str) -> int:
    return (PF_R if "r" in perms else 0) | (PF_W if "w" in perms else 0) | (PF_X if "x" in perms else 0)


def section_flags(perms: str) -> int:
    return SHF_ALLOC | (SHF_WRITE if "w" in perms else 0) | (SHF_EXECINSTR if "x" in perms else 0)


def normalize_pointers(image: bytearray, mappings: list[CapturedMapping], base: int, end: int) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for mapping in mappings:
        relative_start, relative_end = mapping.start - base, mapping.end - base
        first = align(relative_start, 8)
        for offset in range(first, relative_end - 7, 8):
            value = struct.unpack_from("<Q", image, offset)[0]
            if base <= value < end:
                normalized = value - base
                struct.pack_into("<Q", image, offset, normalized)
                changes.append({
                    "relative_offset": hex(offset), "runtime_value": hex(value),
                    "normalized_value": hex(normalized),
                })
    return changes


def embedded_elf_candidates(data: bytes, maximum: int = 256) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    cursor = 0
    while len(result) < maximum:
        offset = data.find(b"\x7fELF", cursor)
        if offset < 0:
            break
        cursor = offset + 1
        if offset + 0x34 > len(data):
            continue
        elf_class, encoding, version = data[offset + 4:offset + 7]
        if elf_class not in (1, 2) or encoding not in (1, 2) or version != 1:
            continue
        order = "<" if encoding == 1 else ">"
        try:
            if elf_class == 2:
                fields = struct.unpack_from(order + "HHIQQQIHHHHHH", data, offset + 16)
                elf_type, machine, entry, phoff, shoff = fields[0], fields[1], fields[3], fields[4], fields[5]
                ehsize, phentsize, phnum, shentsize, shnum = fields[7], fields[8], fields[9], fields[10], fields[11]
                expected_ehsize, expected_phentsize, expected_shentsize = 64, 56, 64
            else:
                fields = struct.unpack_from(order + "HHIIIIIHHHHHH", data, offset + 16)
                elf_type, machine, entry, phoff, shoff = fields[0], fields[1], fields[3], fields[4], fields[5]
                ehsize, phentsize, phnum, shentsize, shnum = fields[7], fields[8], fields[9], fields[10], fields[11]
                expected_ehsize, expected_phentsize, expected_shentsize = 52, 32, 40
        except struct.error:
            continue
        available = len(data) - offset
        ph_valid = not phnum or (phentsize >= expected_phentsize and phoff + phentsize * phnum <= available)
        sh_valid = not shnum or (shoff and shentsize >= expected_shentsize and shoff + shentsize * shnum <= available)
        if ehsize != expected_ehsize or elf_type not in (1, 2, 3, 4) or not machine or not ph_valid or not sh_valid:
            continue
        result.append({
            "relative_offset": hex(offset), "class": 64 if elf_class == 2 else 32,
            "endian": "little" if encoding == 1 else "big", "type": elf_type,
            "machine": machine, "entry": hex(entry), "phoff": hex(phoff), "phnum": phnum,
            "shoff": hex(shoff), "shnum": shnum, "header_tables_in_raw": True,
            "claim_boundary": "embedded candidate only; main-inner identity requires handoff/PC provenance",
        })
    return result


def build_analysis_elf(image: bytes, mappings: list[CapturedMapping], base: int) -> tuple[bytes, list[dict[str, object]]]:
    phnum = len(mappings)
    header_end = 64 + phnum * 56
    cursor = align(header_end)
    output = bytearray(cursor)
    placements: list[dict[str, object]] = []
    for index, mapping in enumerate(mappings, 1):
        relative = mapping.start - base
        page_offset = relative % PAGE
        file_offset = align(cursor - page_offset) + page_offset
        if file_offset < cursor:
            file_offset += PAGE
        output.extend(b"\0" * (file_offset - len(output)))
        segment_data = image[relative:relative + mapping.size]
        output.extend(segment_data)
        placements.append({
            "index": index, "relative_start": relative, "relative_end": relative + mapping.size,
            "file_offset": file_offset, "size": mapping.size,
            "perms": mapping.perms, "name": mapping.name,
        })
        cursor = len(output)

    names = bytearray(b"\0")
    name_offsets: dict[str, int] = {"": 0}
    section_names: list[str] = []
    counters: collections.Counter[str] = collections.Counter()
    for placement in placements:
        kind = "rx" if "x" in str(placement["perms"]) else "rw" if "w" in str(placement["perms"]) else "ro"
        counters[kind] += 1
        name = f".inner.{kind}" + (f".{counters[kind]}" if counters[kind] > 1 else "")
        name_offsets[name] = len(names)
        names.extend(name.encode("ascii") + b"\0")
        section_names.append(name)
    name_offsets[".shstrtab"] = len(names)
    names.extend(b".shstrtab\0")
    shstr_offset = len(output)
    output.extend(names)
    shoff = align(len(output), 8)
    output.extend(b"\0" * (shoff - len(output)))

    section_headers = [struct.pack("<IIQQQQIIQQ", 0, SHT_NULL, 0, 0, 0, 0, 0, 0, 0, 0)]
    for name, placement in zip(section_names, placements):
        section_headers.append(struct.pack(
            "<IIQQQQIIQQ", name_offsets[name], SHT_PROGBITS,
            section_flags(str(placement["perms"])), int(placement["relative_start"]),
            int(placement["file_offset"]), int(placement["size"]), 0, 0, PAGE, 0,
        ))
    shstr_index = len(section_headers)
    section_headers.append(struct.pack(
        "<IIQQQQIIQQ", name_offsets[".shstrtab"], SHT_STRTAB, 0, 0,
        shstr_offset, len(names), 0, 0, 1, 0,
    ))
    for header in section_headers:
        output.extend(header)

    ident = b"\x7fELF\x02\x01\x01\x00" + b"\0" * 8
    output[:64] = struct.pack(
        "<16sHHIQQQIHHHHHH", ident, 3, EM_AARCH64, 1, 0, 64, shoff, 0,
        64, 56, phnum, 64, len(section_headers), shstr_index,
    )
    offset = 64
    for placement in placements:
        output[offset:offset + 56] = struct.pack(
            "<IIQQQQQQ", PT_LOAD, permission_flags(str(placement["perms"])),
            int(placement["file_offset"]), int(placement["relative_start"]),
            int(placement["relative_start"]), int(placement["size"]),
            int(placement["size"]), PAGE,
        )
        offset += 56
    return bytes(output), placements


def command_rebuild(args: argparse.Namespace) -> int:
    if args.base % PAGE or args.end % PAGE or args.base >= args.end:
        raise SystemExit("--base/--end must be ascending page-aligned addresses")
    mappings = load_capture(args.capture_dir, args.base, args.end)
    image = bytearray(args.end - args.base)
    for mapping in mappings:
        relative = mapping.start - args.base
        image[relative:relative + mapping.size] = mapping.data
    raw = bytes(image)
    embedded_candidates = embedded_elf_candidates(raw)
    analysis_image = bytearray(raw)
    changes = normalize_pointers(analysis_image, mappings, args.base, args.end) if args.normalize_pointers else []
    analysis_elf, placements = build_analysis_elf(bytes(analysis_image), mappings, args.base)

    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_prefix.with_name(args.out_prefix.name + ".mem")
    elf_path = args.out_prefix.with_name(args.out_prefix.name + ".analysis.elf")
    manifest_path = args.out_prefix.with_name(args.out_prefix.name + ".manifest.json")
    raw_path.write_bytes(raw)
    elf_path.write_bytes(analysis_elf)
    manifest = {
        "schema": "xigong.funk-hikari.inner-rebuild/v1",
        "capture": str(args.capture_dir.resolve()),
        "runtime_base": hex(args.base), "runtime_end": hex(args.end),
        "raw_memory": {
            "path": str(raw_path.resolve()), "size": len(raw), "sha256": sha256(raw),
            "semantics": "captured bytes at relative offsets; unmapped gaps are zero",
        },
        "analysis_elf": {
            "path": str(elf_path.resolve()), "size": len(analysis_elf),
            "sha256": sha256(analysis_elf), "entry": "unknown/0",
            "standalone_executable": False,
            "pointer_normalizations": len(changes),
        },
        "embedded_elf_candidates": embedded_candidates,
        "primary_inner_identity": "not inferred from embedded ELF magic; bind loader handoff or active PC/LR",
        "mappings": [{
            "runtime_start": hex(mapping.start), "runtime_end": hex(mapping.end),
            "relative_start": hex(mapping.start - args.base),
            "relative_end": hex(mapping.end - args.base),
            "perms": mapping.perms, "name": mapping.name,
            "source": str(mapping.source_path), "source_sha256": sha256_file(mapping.source_path),
            "captured_slice_sha256": sha256(mapping.data),
            "analysis_file_offset": hex(int(placement["file_offset"])),
        } for mapping, placement in zip(mappings, placements)],
        "pointer_normalization": changes,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "raw_memory": manifest["raw_memory"], "analysis_elf": manifest["analysis_elf"],
        "manifest": str(manifest_path.resolve()), "mappings": len(mappings),
        "embedded_elf_candidates": len(embedded_candidates),
    }, ensure_ascii=False, indent=2))
    return 0


def classify_text(text: str) -> str | None:
    if not text or not all(character.isprintable() or character in "\t\r\n" for character in text):
        return None
    cjk = sum(
        "CJK" in unicodedata.name(character, "") or "IDEOGRAPH" in unicodedata.name(character, "")
        for character in text
    )
    if cjk:
        return "cjk"
    return "ascii" if all(ord(character) < 0x7F for character in text) else "unicode"


def utf8_width(data: bytes, offset: int) -> int:
    byte = data[offset]
    if byte in (9, 10, 13) or 0x20 <= byte <= 0x7E:
        return 1
    width = 2 if 0xC2 <= byte <= 0xDF else 3 if 0xE0 <= byte <= 0xEF else 4 if 0xF0 <= byte <= 0xF4 else 0
    if not width or offset + width > len(data):
        return 0
    try:
        char = data[offset:offset + width].decode("utf-8")
    except UnicodeDecodeError:
        return 0
    return width if char.isprintable() else 0


def extract_utf8(data: bytes, minimum: int, maximum: int) -> list[tuple[int, str, bytes]]:
    result: list[tuple[int, str, bytes]] = []
    index = 0
    while index < len(data):
        start, cursor = index, index
        exceeded = False
        while cursor < len(data) and data[cursor] != 0:
            width = utf8_width(data, cursor)
            if not width:
                break
            cursor += width
            if cursor - start > maximum:
                exceeded = True
                break
        if exceeded:
            index = cursor
            continue
        if cursor < len(data) and data[cursor] == 0 and minimum <= cursor - start <= maximum:
            raw = data[start:cursor]
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if classify_text(text):
                result.append((start, text, raw))
                index = cursor + 1
                continue
        index = cursor + 1 if cursor > start else start + 1
    return result


def extract_utf8_nul_tokens(data: bytes, minimum: int, maximum: int) -> list[tuple[int, str, bytes]]:
    """Conservative default: accept complete NUL-delimited tokens only."""
    result: list[tuple[int, str, bytes]] = []
    start = 0
    for end in range(len(data) + 1):
        if end < len(data) and data[end] != 0:
            continue
        raw = data[start:end]
        token_offset = start
        start = end + 1
        if not minimum <= len(raw) <= maximum:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if classify_text(text):
            result.append((token_offset, text, raw))
    return result


def extract_utf16le(data: bytes, minimum: int, maximum: int) -> list[tuple[int, str, bytes]]:
    result: list[tuple[int, str, bytes]] = []
    for parity in (0, 1):
        index = parity
        while index + 3 < len(data):
            start, cursor, chars = index, index, 0
            exceeded = False
            while cursor + 1 < len(data):
                unit = data[cursor:cursor + 2]
                if unit == b"\0\0":
                    break
                try:
                    char = unit.decode("utf-16le")
                except UnicodeDecodeError:
                    break
                if not (char.isprintable() or char in "\t\r\n"):
                    break
                cursor += 2
                chars += 1
                if chars > maximum:
                    exceeded = True
                    break
            if exceeded:
                index = cursor + 2
                continue
            if cursor + 1 < len(data) and data[cursor:cursor + 2] == b"\0\0" and minimum <= chars <= maximum:
                raw = data[start:cursor]
                text = raw.decode("utf-16le", errors="strict")
                if classify_text(text):
                    result.append((start, text, raw))
                    index = cursor + 2
                    continue
            index = cursor + 2 if cursor > start else start + 2
    return result


def escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def command_strings(args: argparse.Namespace) -> int:
    data = args.input.read_bytes()
    encodings = {item.strip().lower() for item in args.encodings.split(",") if item.strip()}
    found: list[tuple[int, str, bytes, str]] = []
    if "utf-8" in encodings or "utf8" in encodings:
        extractor = extract_utf8_nul_tokens if args.mode == "nul-token" else extract_utf8
        found.extend((offset, text, raw, "utf-8") for offset, text, raw in extractor(data, args.minimum, args.maximum))
    if "utf-16le" in encodings or "utf16le" in encodings:
        found.extend((offset, text, raw, "utf-16le") for offset, text, raw in extract_utf16le(data, args.minimum, args.maximum))
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for offset, text, raw, encoding in sorted(found):
        kind = classify_text(text)
        if kind is None:
            continue
        key = (encoding, text)
        record = grouped.get(key)
        position = {"offset": hex(offset), "va": hex(args.base + offset)}
        if record is None:
            grouped[key] = {
                "text": text, "encoding": encoding, "kind": kind,
                "byte_length": len(raw), "positions": [position],
            }
        elif len(record["positions"]) < args.max_positions:
            record["positions"].append(position)
    records = sorted(grouped.values(), key=lambda item: int(str(item["positions"][0]["offset"]), 16))
    counts = collections.Counter(f"{item['encoding']}:{item['kind']}" for item in records)
    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out_prefix.with_name(args.out_prefix.name + ".json")
    tsv_path = args.out_prefix.with_name(args.out_prefix.name + ".tsv")
    txt_path = args.out_prefix.with_name(args.out_prefix.name + ".txt")
    report = {
        "schema": "xigong.funk-hikari.plain-strings/v1",
        "input": str(args.input.resolve()), "input_size": len(data),
        "input_sha256": sha256(data), "base": hex(args.base),
        "minimum": args.minimum, "maximum": args.maximum,
        "counts": dict(counts), "unique_strings": len(records), "strings": records,
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tsv_path.write_text(
        "offset\tva\tencoding\tkind\tbytes\ttext\n" + "".join(
            f"{item['positions'][0]['offset']}\t{item['positions'][0]['va']}\t{item['encoding']}\t"
            f"{item['kind']}\t{item['byte_length']}\t{escaped(str(item['text']))}\n"
            for item in records
        ), encoding="utf-8",
    )
    txt_path.write_text("\n".join(escaped(str(item["text"])) for item in records) + "\n", encoding="utf-8")
    print(json.dumps({
        "strings": len(records), "counts": dict(counts), "json": str(json_path.resolve()),
        "tsv": str(tsv_path.resolve()), "txt": str(txt_path.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


def validate_outer_elf(data: bytes) -> dict[str, object]:
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError("outer is not an ELF file")
    elf_class, endian = data[4], data[5]
    if elf_class not in (1, 2) or endian not in (1, 2):
        raise ValueError("unsupported ELF class/endian")
    order = "<" if endian == 1 else ">"
    machine = struct.unpack_from(order + "H", data, 18)[0]
    return {"elf_class": 32 if elf_class == 1 else 64, "endian": "little" if endian == 1 else "big", "machine": machine}


def build_trailer(metadata: dict[str, object]) -> bytes:
    encoded = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > CARRIER_TRAILER_SIZE - 0x40:
        raise ValueError("carrier metadata does not fit trailer page")
    trailer = bytearray(CARRIER_TRAILER_SIZE)
    trailer[:len(CARRIER_MAGIC)] = CARRIER_MAGIC
    struct.pack_into("<I", trailer, 0x20, len(encoded))
    trailer[0x40:0x40 + len(encoded)] = encoded
    return bytes(trailer)


def command_carrier(args: argparse.Namespace) -> int:
    outer, inner = args.outer.read_bytes(), args.inner.read_bytes()
    elf_info = validate_outer_elf(outer)
    expected = args.runtime_end - args.runtime_base
    if expected <= 0 or len(inner) != expected:
        raise ValueError(f"inner size mismatch: expected {expected}, got {len(inner)}")
    trailer_offset = align(len(outer))
    payload_offset = trailer_offset + CARRIER_TRAILER_SIZE
    metadata = {
        "schema": "xigong.funk-hikari.plain-carrier/v1",
        "outer_size": len(outer), "outer_sha256": sha256(outer),
        "trailer_offset": trailer_offset, "trailer_size": CARRIER_TRAILER_SIZE,
        "payload_offset": payload_offset, "payload_size": len(inner),
        "payload_sha256": sha256(inner), "runtime_base": args.runtime_base,
        "runtime_end": args.runtime_end,
        "execution_model": "outer loader unchanged; plaintext runtime image carried in EOF overlay",
    }
    output = bytearray(outer)
    output.extend(b"\0" * (trailer_offset - len(output)))
    output.extend(build_trailer(metadata))
    output.extend(inner)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    if os.name != "nt":
        args.output.chmod(args.outer.stat().st_mode)
    manifest = {
        **metadata, "outer_path": str(args.outer.resolve()), "inner_path": str(args.inner.resolve()),
        "output_path": str(args.output.resolve()), "output_size": len(output),
        "output_sha256": sha256(output), "outer_elf": elf_info,
        "outer_prefix_preserved": bytes(output[:len(outer)]) == outer,
        "outer_program_headers_modified": False,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def parse_trailer(data: bytes, manifest: dict[str, object] | None = None) -> tuple[dict[str, object], int]:
    offsets: list[int] = []
    if manifest is not None and "trailer_offset" in manifest:
        offsets.append(parse_int(manifest["trailer_offset"]))
    cursor = 0
    while True:
        found = data.find(CARRIER_MAGIC, cursor)
        if found < 0:
            break
        offsets.append(found)
        cursor = found + 1
    for offset in dict.fromkeys(offsets):
        if offset + CARRIER_TRAILER_SIZE > len(data) or data[offset:offset + len(CARRIER_MAGIC)] != CARRIER_MAGIC:
            continue
        length = struct.unpack_from("<I", data, offset + 0x20)[0]
        if not 0 < length <= CARRIER_TRAILER_SIZE - 0x40:
            continue
        try:
            metadata = json.loads(data[offset + 0x40:offset + 0x40 + length].decode("utf-8"))
        except Exception:
            continue
        outer_size = parse_int(metadata.get("outer_size", -1))
        payload_offset = parse_int(metadata.get("payload_offset", -1))
        payload_size = parse_int(metadata.get("payload_size", -1))
        if not (0 <= outer_size <= offset and 0 <= payload_offset <= len(data) and 0 <= payload_size <= len(data) - payload_offset):
            continue
        if sha256(data[:outer_size]) != metadata.get("outer_sha256"):
            continue
        if sha256(data[payload_offset:payload_offset + payload_size]) != metadata.get("payload_sha256"):
            continue
        return metadata, offset
    raise ValueError("no self-consistent XG-FUNK-HIKARI carrier trailer found")


def command_verify_carrier(args: argparse.Namespace) -> int:
    data = args.input.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    metadata, trailer_offset = parse_trailer(data, manifest)
    payload_offset, payload_size = parse_int(metadata["payload_offset"]), parse_int(metadata["payload_size"])
    needle_results = []
    for needle in args.needle:
        raw = needle.encode(args.needle_encoding)
        positions: list[str] = []
        cursor = 0
        while len(positions) < 16:
            found = data.find(raw, cursor)
            if found < 0:
                break
            positions.append(hex(found))
            cursor = found + 1
        needle_results.append({"text": needle, "encoding": args.needle_encoding, "positions": positions, "found": bool(positions)})
    report = {
        "schema": "xigong.funk-hikari.carrier-verification/v1",
        "input": str(args.input.resolve()), "input_size": len(data), "input_sha256": sha256(data),
        "trailer_offset": hex(trailer_offset), "metadata": metadata,
        "outer_prefix_hash_valid": sha256(data[:parse_int(metadata["outer_size"])]) == metadata["outer_sha256"],
        "payload_hash_valid": sha256(data[payload_offset:payload_offset + payload_size]) == metadata["payload_sha256"],
        "needles": needle_results,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["found"] for item in needle_results) else (0 if not needle_results else 1)


def command_extract_carrier(args: argparse.Namespace) -> int:
    data = args.input.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    metadata, _ = parse_trailer(data, manifest)
    outer_size = parse_int(metadata["outer_size"])
    payload_offset, payload_size = parse_int(metadata["payload_offset"]), parse_int(metadata["payload_size"])
    args.outer_out.parent.mkdir(parents=True, exist_ok=True)
    args.inner_out.parent.mkdir(parents=True, exist_ok=True)
    args.outer_out.write_bytes(data[:outer_size])
    args.inner_out.write_bytes(data[payload_offset:payload_offset + payload_size])
    print(json.dumps({
        "outer": {"path": str(args.outer_out.resolve()), "sha256": sha256_file(args.outer_out)},
        "inner": {"path": str(args.inner_out.resolve()), "sha256": sha256_file(args.inner_out)},
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture selected readable mappings through adb/root")
    capture.add_argument("--serial", required=True)
    capture.add_argument("--pid", required=True, type=int)
    capture.add_argument("--range", action="append", type=parse_range, default=[])
    capture.add_argument("--target-name", default="")
    capture.add_argument("--out-dir", required=True, type=Path)
    capture.add_argument("--adb", default="adb")
    capture.add_argument("--max-mapping", type=lambda value: int(value, 0), default=0x10000000)
    capture.add_argument("--max-total", type=lambda value: int(value, 0), default=0x40000000)
    capture.add_argument("--timeout", type=float, default=120.0)
    capture.set_defaults(func=command_capture)

    compare = sub.add_parser("compare-captures", help="verify two same-stage captures mapping-by-mapping")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    compare.add_argument("--out", type=Path)
    compare.set_defaults(func=command_compare_captures)

    rebuild = sub.add_parser("rebuild", help="build raw relative image and IDA analysis ELF")
    rebuild.add_argument("capture_dir", type=Path)
    rebuild.add_argument("--base", required=True, type=lambda value: int(value, 0))
    rebuild.add_argument("--end", required=True, type=lambda value: int(value, 0))
    rebuild.add_argument("--out-prefix", required=True, type=Path)
    rebuild.add_argument("--normalize-pointers", action="store_true")
    rebuild.set_defaults(func=command_rebuild)

    strings = sub.add_parser("strings", help="extract searchable NUL-terminated plaintext strings")
    strings.add_argument("input", type=Path)
    strings.add_argument("--base", type=lambda value: int(value, 0), default=0)
    strings.add_argument("--out-prefix", required=True, type=Path)
    strings.add_argument("--minimum", type=int, default=4)
    strings.add_argument("--maximum", type=int, default=4096)
    strings.add_argument("--encodings", default="utf-8")
    strings.add_argument("--mode", choices=("nul-token", "scan"), default="nul-token")
    strings.add_argument("--max-positions", type=int, default=64)
    strings.set_defaults(func=command_strings)

    carrier = sub.add_parser("carrier", help="append plaintext raw image to a verified runnable outer ELF")
    carrier.add_argument("outer", type=Path)
    carrier.add_argument("inner", type=Path)
    carrier.add_argument("--runtime-base", required=True, type=lambda value: int(value, 0))
    carrier.add_argument("--runtime-end", required=True, type=lambda value: int(value, 0))
    carrier.add_argument("--output", required=True, type=Path)
    carrier.add_argument("--manifest", required=True, type=Path)
    carrier.set_defaults(func=command_carrier)

    verify = sub.add_parser("verify-carrier", help="verify carrier prefix/payload hashes and plaintext needles")
    verify.add_argument("input", type=Path)
    verify.add_argument("--manifest", type=Path)
    verify.add_argument("--needle", action="append", default=[])
    verify.add_argument("--needle-encoding", default="utf-8")
    verify.add_argument("--out", type=Path)
    verify.set_defaults(func=command_verify_carrier)

    extract = sub.add_parser("extract-carrier", help="recover outer prefix and inner payload from carrier")
    extract.add_argument("input", type=Path)
    extract.add_argument("--manifest", type=Path)
    extract.add_argument("--outer-out", required=True, type=Path)
    extract.add_argument("--inner-out", required=True, type=Path)
    extract.set_defaults(func=command_extract_carrier)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
