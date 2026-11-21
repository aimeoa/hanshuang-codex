#!/usr/bin/env python3
"""Fallback DEX capture through root-readable /proc/<pid>/mem over ADB."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from lib.dex import validate_dex_bytes


MAP_LINE = re.compile(
    r"^(?P<start>[0-9a-f]+)-(?P<end>[0-9a-f]+)\s+(?P<perms>\S+)\s+(?P<offset>\S+)\s+(?P<dev>\S+)\s+(?P<inode>\S+)\s*(?P<path>.*)$"
)
DEX_MAGIC = re.compile(br"dex\n.\d\d\x00")
PAGE_SIZE = 4096


@dataclass(frozen=True)
class MemoryMap:
    start: int
    end: int
    perms: str
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start


def adb_output(adb: str, serial: str | None, command: str) -> bytes:
    invocation = [adb]
    if serial:
        invocation.extend(["-s", serial])
    invocation.extend(["exec-out", "su", "-c", command])
    result = subprocess.run(invocation, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"ADB command failed: {command}")
    return result.stdout


def parse_maps(raw: bytes) -> list[MemoryMap]:
    maps: list[MemoryMap] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        match = MAP_LINE.match(line)
        if match:
            maps.append(
                MemoryMap(
                    start=int(match["start"], 16),
                    end=int(match["end"], 16),
                    perms=match["perms"],
                    path=match["path"].strip(),
                )
            )
    if not maps:
        raise RuntimeError("could not parse /proc maps")
    return maps


def readable_spans(maps: list[MemoryMap], min_size: int) -> list[tuple[int, int, list[MemoryMap]]]:
    spans: list[tuple[int, int, list[MemoryMap]]] = []
    current: list[MemoryMap] = []
    for mapping in maps:
        if not mapping.perms.startswith("r"):
            if current:
                spans.append((current[0].start, current[-1].end, current))
                current = []
            continue
        if current and mapping.start != current[-1].end:
            spans.append((current[0].start, current[-1].end, current))
            current = []
        current.append(mapping)
    if current:
        spans.append((current[0].start, current[-1].end, current))
    return [span for span in spans if span[1] - span[0] >= min_size]


def read_memory(adb: str, serial: str | None, pid: int, address: int, size: int) -> bytes:
    page_start = address // PAGE_SIZE
    in_page = address % PAGE_SIZE
    page_count = (in_page + size + PAGE_SIZE - 1) // PAGE_SIZE
    raw = adb_output(adb, serial, f"dd if=/proc/{pid}/mem bs={PAGE_SIZE} skip={page_start} count={page_count} 2>/dev/null")
    chunk = raw[in_page:in_page + size]
    if len(chunk) != size:
        raise RuntimeError(f"short read at 0x{address:x}: {len(chunk)}/{size}")
    return chunk


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--serial", help="ADB serial; omit when one device is connected")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-span-kib", type=int, default=256)
    parser.add_argument("--max-dex-mib", type=int, default=256)
    parser.add_argument("--max-scan-mib", type=int, default=768, help="Total readable memory budget for header scanning")
    parser.add_argument("--chunk-kib", type=int, default=1024)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"output directory is not empty: {args.output}")
    if min(args.min_span_kib, args.max_dex_mib, args.max_scan_mib, args.chunk_kib) < 1:
        raise SystemExit("capture sizes must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    maps = parse_maps(adb_output(args.adb, args.serial, f"cat /proc/{args.pid}/maps"))
    spans = readable_spans(maps, args.min_span_kib * 1024)
    max_scan = args.max_scan_mib * 1024 * 1024
    max_dex = args.max_dex_mib * 1024 * 1024
    chunk_size = args.chunk_kib * 1024
    scanned = 0
    records: list[dict[str, object]] = []
    seen_addresses: set[int] = set()
    seen_hashes: set[str] = set()

    for start, end, span_maps in spans:
        if scanned >= max_scan:
            break
        cursor = start
        previous = b""
        while cursor < end and scanned < max_scan:
            count = min(chunk_size, end - cursor, max_scan - scanned)
            try:
                data = read_memory(args.adb, args.serial, args.pid, cursor, count)
            except RuntimeError:
                break
            searched = previous + data
            base = cursor - len(previous)
            for match in DEX_MAGIC.finditer(searched):
                address = base + match.start()
                if address in seen_addresses or address + 0x70 > end:
                    continue
                seen_addresses.add(address)
                local = address - cursor
                if local < 0 or local + 0x24 > len(data):
                    try:
                        header = read_memory(args.adb, args.serial, args.pid, address, 0x70)
                    except RuntimeError:
                        continue
                else:
                    header = data[local:local + 0x70]
                size = int.from_bytes(header[0x20:0x24], "little")
                if size < 0x70 or size > max_dex or address + size > end:
                    continue
                try:
                    dex = read_memory(args.adb, args.serial, args.pid, address, size)
                except RuntimeError:
                    continue
                target = args.output / f"dex_{len(records):03d}_0x{address:x}_{size}.dex"
                target.write_bytes(dex)
                digest = sha256_file(target)
                if digest in seen_hashes:
                    target.unlink()
                    continue
                seen_hashes.add(digest)
                validation = validate_dex_bytes(dex)
                records.append(
                    {
                        "path": target.name,
                        "address": f"0x{address:x}",
                        "size": size,
                        "sha256": digest,
                        "valid": validation.valid,
                        "validation": validation.as_dict(include_classes=False),
                        "maps": [asdict(mapping) for mapping in span_maps],
                    }
                )
                print(f"recovered {target.name}")
            scanned += count
            previous = searched[-7:]
            cursor += count

    (args.output / "capture.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not records:
        raise SystemExit("no DEX headers were found in the readable scan budget")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
