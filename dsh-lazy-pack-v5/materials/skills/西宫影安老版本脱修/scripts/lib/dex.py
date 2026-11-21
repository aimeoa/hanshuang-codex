"""Small, dependency-free DEX reader used for validation and inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import struct
import zlib


DEX_HEADER_SIZE = 0x70
NO_INDEX = 0xFFFFFFFF
ENDIAN_CONSTANT = 0x12345678


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_uleb(data: bytes | bytearray, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        if offset >= len(data):
            raise ValueError("ULEB128 extends past the DEX")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("ULEB128 is longer than five bytes")


def descriptor_to_dot(descriptor: str) -> str:
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    return descriptor


@dataclass
class DexReport:
    valid: bool
    file_size: int
    magic: str
    sha256: str
    sha1_valid: bool | None
    adler32_valid: bool | None
    class_count: int | None
    classes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self, include_classes: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "valid": self.valid,
            "file_size": self.file_size,
            "magic": self.magic,
            "sha256": self.sha256,
            "sha1_valid": self.sha1_valid,
            "adler32_valid": self.adler32_valid,
            "class_count": self.class_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if include_classes:
            result["classes"] = self.classes
        return result


class DexView:
    """Read the string, type, and class tables from a structurally valid DEX."""

    def __init__(self, data: bytes | bytearray) -> None:
        self.data = data
        self.strings = self._read_strings()
        self.types = self._read_types()

    def _read_strings(self) -> list[str]:
        count = u32(self.data, 56)
        offset = u32(self.data, 60)
        strings: list[str] = []
        for index in range(count):
            item_offset = u32(self.data, offset + index * 4)
            _, cursor = read_uleb(self.data, item_offset)
            end = self.data.index(0, cursor)
            strings.append(bytes(self.data[cursor:end]).decode("utf-8", errors="replace"))
        return strings

    def _read_types(self) -> list[str]:
        count = u32(self.data, 64)
        offset = u32(self.data, 68)
        types: list[str] = []
        for index in range(count):
            string_index = u32(self.data, offset + index * 4)
            types.append(self.strings[string_index])
        return types

    def class_definitions(self) -> list[dict[str, object]]:
        count = u32(self.data, 96)
        offset = u32(self.data, 100)
        result: list[dict[str, object]] = []
        for index in range(count):
            item = offset + index * 32
            class_index = u32(self.data, item)
            super_index = u32(self.data, item + 8)
            result.append(
                {
                    "descriptor": self.types[class_index],
                    "name": descriptor_to_dot(self.types[class_index]),
                    "super_descriptor": None if super_index == NO_INDEX else self.types[super_index],
                    "super_name": None if super_index == NO_INDEX else descriptor_to_dot(self.types[super_index]),
                    "access_flags": u32(self.data, item + 4),
                }
            )
        return result


def _check_table(
    data: bytes | bytearray,
    size_offset: int,
    offset_offset: int,
    item_width: int,
    label: str,
    errors: list[str],
) -> None:
    count = u32(data, size_offset)
    offset = u32(data, offset_offset)
    if count == 0:
        return
    if offset < DEX_HEADER_SIZE or offset > len(data):
        errors.append(f"{label}_off is outside the DEX")
        return
    if count > (len(data) - offset) // item_width:
        errors.append(f"{label} table extends past the DEX")


def validate_dex_bytes(data: bytes | bytearray) -> DexReport:
    digest = hashlib.sha256(data).hexdigest()
    magic = bytes(data[:8]).decode("ascii", errors="replace") if data else ""
    errors: list[str] = []
    warnings: list[str] = []
    sha1_valid: bool | None = None
    adler32_valid: bool | None = None
    class_count: int | None = None
    classes: list[str] = []

    if len(data) < DEX_HEADER_SIZE:
        errors.append("input is smaller than a DEX header")
    elif data[:4] != b"dex\n" or data[7] != 0:
        errors.append("unsupported DEX magic")
    else:
        declared_size = u32(data, 32)
        if declared_size != len(data):
            errors.append(f"file_size mismatch: header={declared_size} actual={len(data)}")
        if u32(data, 36) != DEX_HEADER_SIZE:
            errors.append("unexpected DEX header_size")
        if u32(data, 40) != ENDIAN_CONSTANT:
            errors.append("unsupported DEX endian tag")
        sha1_valid = hashlib.sha1(data[32:]).digest() == bytes(data[12:32])
        adler32_valid = (zlib.adler32(data[12:]) & 0xFFFFFFFF) == u32(data, 8)
        if not sha1_valid:
            warnings.append("DEX SHA-1 signature does not match header")
        if not adler32_valid:
            warnings.append("DEX Adler-32 checksum does not match header")
        for size_offset, offset_offset, width, label in (
            (56, 60, 4, "string_ids"),
            (64, 68, 4, "type_ids"),
            (72, 76, 12, "proto_ids"),
            (80, 84, 8, "field_ids"),
            (88, 92, 8, "method_ids"),
            (96, 100, 32, "class_defs"),
        ):
            _check_table(data, size_offset, offset_offset, width, label, errors)
        map_offset = u32(data, 52)
        if map_offset < DEX_HEADER_SIZE or map_offset + 4 > len(data):
            errors.append("map_off is outside the DEX")
        elif u32(data, map_offset) > (len(data) - map_offset - 4) // 12:
            errors.append("map_list extends past the DEX")

    if not errors:
        try:
            view = DexView(data)
            definitions = view.class_definitions()
            class_count = len(definitions)
            classes = [str(item["descriptor"]) for item in definitions]
        except (IndexError, ValueError, struct.error) as exc:
            errors.append(f"unable to read DEX tables: {exc}")

    return DexReport(
        valid=not errors,
        file_size=len(data),
        magic=magic,
        sha256=digest,
        sha1_valid=sha1_valid,
        adler32_valid=adler32_valid,
        class_count=class_count,
        classes=classes,
        errors=errors,
        warnings=warnings,
    )


def validate_dex_path(path: object) -> DexReport:
    from pathlib import Path

    return validate_dex_bytes(Path(path).read_bytes())
