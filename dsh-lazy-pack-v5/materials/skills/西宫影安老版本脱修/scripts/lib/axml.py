"""Minimal compiled Android XML reader/editor for manifest component names."""

from __future__ import annotations

from dataclasses import dataclass
import struct


RES_XML_TYPE = 0x0003
RES_STRING_POOL_TYPE = 0x0001
RES_XML_START_ELEMENT_TYPE = 0x0102
UTF8_FLAG = 0x00000100
TYPE_STRING = 0x03
NO_INDEX = 0xFFFFFFFF
ANDROID_NS = "http://schemas.android.com/apk/res/android"


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def put_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def _decode_length8(data: bytes, offset: int) -> tuple[int, int]:
    first = data[offset]
    if first & 0x80:
        return ((first & 0x7F) << 8) | data[offset + 1], offset + 2
    return first, offset + 1


def _decode_length16(data: bytes, offset: int) -> tuple[int, int]:
    first = u16(data, offset)
    if first & 0x8000:
        return ((first & 0x7FFF) << 16) | u16(data, offset + 2), offset + 4
    return first, offset + 2


def _encode_length8(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    if value < 0x8000:
        return bytes([0x80 | (value >> 8), value & 0xFF])
    raise ValueError("Android UTF-8 string is too long")


def _encode_length16(value: int) -> bytes:
    if value < 0x8000:
        return struct.pack("<H", value)
    if value < 0x80000000:
        return struct.pack("<HH", 0x8000 | (value >> 16), value & 0xFFFF)
    raise ValueError("Android UTF-16 string is too long")


@dataclass
class StringPool:
    offset: int
    header_size: int
    size: int
    string_count: int
    style_count: int
    flags: int
    strings_start: int
    styles_start: int
    offsets: list[int]
    raw: bytes

    @property
    def utf8(self) -> bool:
        return bool(self.flags & UTF8_FLAG)

    def value(self, index: int) -> str:
        if index == NO_INDEX:
            return ""
        if not 0 <= index < self.string_count:
            raise ValueError(f"invalid string-pool index: {index}")
        cursor = self.strings_start + self.offsets[index]
        if self.utf8:
            _, cursor = _decode_length8(self.raw, cursor)
            byte_count, cursor = _decode_length8(self.raw, cursor)
            return self.raw[cursor : cursor + byte_count].decode("utf-8")
        char_count, cursor = _decode_length16(self.raw, cursor)
        return self.raw[cursor : cursor + char_count * 2].decode("utf-16le")

    def append(self, value: str) -> tuple[bytes, int]:
        string_offsets_end = self.header_size + self.string_count * 4
        style_offsets_end = string_offsets_end + self.style_count * 4
        string_data_end = self.styles_start if self.styles_start else self.size
        string_data = self.raw[self.strings_start:string_data_end]
        styles = self.raw[string_data_end:self.size]
        if self.utf8:
            encoded = value.encode("utf-8")
            addition = _encode_length8(len(value)) + _encode_length8(len(encoded)) + encoded + b"\x00"
        else:
            encoded = value.encode("utf-16le")
            addition = _encode_length16(len(value)) + encoded + b"\x00\x00"
        addition += b"\x00" * ((-len(addition)) % 4)

        offsets = self.offsets + [len(string_data)]
        output = bytearray(self.raw[:self.header_size])
        output.extend(struct.pack(f"<{len(offsets)}I", *offsets))
        if self.style_count:
            output.extend(self.raw[string_offsets_end:style_offsets_end])
        output.extend(string_data)
        output.extend(addition)
        output.extend(styles)
        put_u32(output, 4, len(output))
        put_u32(output, 8, self.string_count + 1)
        put_u32(output, 20, self.strings_start + 4)
        put_u32(output, 24, self.styles_start + 4 + len(addition) if self.styles_start else 0)
        return bytes(output), self.string_count


def parse_string_pool(raw: bytes | bytearray, offset: int = 8) -> StringPool:
    if u16(raw, offset) != RES_STRING_POOL_TYPE:
        raise ValueError("the first XML child is not a string pool")
    header_size = u16(raw, offset + 2)
    size = u32(raw, offset + 4)
    if header_size < 28 or offset + size > len(raw):
        raise ValueError("malformed Android string pool")
    chunk = bytes(raw[offset:offset + size])
    string_count = u32(chunk, 8)
    style_count = u32(chunk, 12)
    strings_start = u32(chunk, 20)
    styles_start = u32(chunk, 24)
    if strings_start < header_size + string_count * 4 + style_count * 4 or strings_start > size:
        raise ValueError("malformed Android string data offset")
    if styles_start and not strings_start <= styles_start <= size:
        raise ValueError("malformed Android style offset")
    offsets_end = header_size + string_count * 4
    if offsets_end > size:
        raise ValueError("string-offset table extends past the pool")
    offsets = list(struct.unpack_from(f"<{string_count}I", chunk, header_size))
    return StringPool(
        offset=offset,
        header_size=header_size,
        size=size,
        string_count=string_count,
        style_count=style_count,
        flags=u32(chunk, 16),
        strings_start=strings_start,
        styles_start=styles_start,
        offsets=offsets,
        raw=chunk,
    )


def _require_document(raw: bytes | bytearray) -> StringPool:
    if len(raw) < 8 or u16(raw, 0) != RES_XML_TYPE or u16(raw, 2) != 8 or u32(raw, 4) != len(raw):
        raise ValueError("input is not a complete compiled Android XML document")
    return parse_string_pool(raw)


def iter_start_elements(raw: bytes | bytearray) -> list[dict[str, object]]:
    pool = _require_document(raw)
    result: list[dict[str, object]] = []
    cursor = pool.offset + pool.size
    while cursor + 8 <= len(raw):
        chunk_type = u16(raw, cursor)
        header_size = u16(raw, cursor + 2)
        chunk_size = u32(raw, cursor + 4)
        if header_size < 8 or chunk_size < header_size or cursor + chunk_size > len(raw):
            raise ValueError(f"malformed XML chunk at 0x{cursor:x}")
        if chunk_type == RES_XML_START_ELEMENT_TYPE:
            if header_size < 16:
                raise ValueError("malformed XML start element")
            name_index = u32(raw, cursor + 20)
            attr_start = u16(raw, cursor + 24)
            attr_size = u16(raw, cursor + 26)
            attr_count = u16(raw, cursor + 28)
            if attr_size != 20:
                raise ValueError("unsupported XML attribute size")
            attrs_offset = cursor + 16 + attr_start
            if attrs_offset + attr_count * attr_size > cursor + chunk_size:
                raise ValueError("malformed XML attribute table")
            attributes: list[dict[str, object]] = []
            for index in range(attr_count):
                item = attrs_offset + index * attr_size
                raw_value = u32(raw, item + 8)
                data_type = raw[item + 15]
                data_value = u32(raw, item + 16)
                value_index = raw_value if raw_value != NO_INDEX else data_value
                value = pool.value(value_index) if data_type == TYPE_STRING or raw_value != NO_INDEX else data_value
                attributes.append(
                    {
                        "offset": item,
                        "namespace": pool.value(u32(raw, item)),
                        "name": pool.value(u32(raw, item + 4)),
                        "value": value,
                        "data_type": data_type,
                        "raw_value_offset": None if raw_value == NO_INDEX else item + 8,
                    }
                )
            result.append({"name": pool.value(name_index), "offset": cursor, "attributes": attributes})
        cursor += chunk_size
    return result


def manifest_summary(raw: bytes | bytearray) -> dict[str, object]:
    package_name = ""
    application: str | None = None
    components: dict[str, list[dict[str, str]]] = {key: [] for key in ("activity", "activity-alias", "service", "receiver", "provider")}
    for element in iter_start_elements(raw):
        name = str(element["name"])
        attrs = {f"{item['namespace']}:{item['name']}": item["value"] for item in element["attributes"]}
        plain = {str(item["name"]): item["value"] for item in element["attributes"] if not item["namespace"]}
        android = {str(item["name"]): item["value"] for item in element["attributes"] if item["namespace"] == ANDROID_NS}
        if name == "manifest":
            package_name = str(plain.get("package", ""))
        elif name == "application":
            application = str(android["name"]) if "name" in android else None
        elif name in components and "name" in android:
            item = {"name": str(android["name"])}
            if "targetActivity" in android:
                item["targetActivity"] = str(android["targetActivity"])
            components[name].append(item)
    return {"package": package_name, "application": application, "components": components}


def _find_name_attribute(raw: bytes | bytearray, element_name: str, expected_name: str | None) -> tuple[int, int | None]:
    for element in iter_start_elements(raw):
        if element["name"] != element_name:
            continue
        for attribute in element["attributes"]:
            if attribute["namespace"] != ANDROID_NS or attribute["name"] != "name":
                continue
            if expected_name is None or attribute["value"] == expected_name:
                return int(attribute["offset"]), attribute["raw_value_offset"] if attribute["raw_value_offset"] is None else int(attribute["raw_value_offset"])
    if expected_name is None:
        raise ValueError(f"<{element_name}> has no android:name attribute")
    raise ValueError(f"no <{element_name}> with android:name={expected_name!r} was found")


def patch_component_name(raw: bytes, element: str, original_name: str | None, replacement: str) -> bytes:
    pool = _require_document(raw)
    replacement_pool, index = pool.append(replacement)
    patched = bytearray(raw[:pool.offset] + replacement_pool + raw[pool.offset + pool.size:])
    put_u32(patched, 4, len(patched))
    attribute, raw_value_offset = _find_name_attribute(patched, element, original_name)
    if raw_value_offset is not None:
        put_u32(patched, raw_value_offset, index)
    if patched[attribute + 15] != TYPE_STRING:
        raise ValueError(f"<{element}> android:name is not a string")
    put_u32(patched, attribute + 16, index)
    return bytes(patched)


def patch_application_name(raw: bytes, replacement: str) -> bytes:
    return patch_component_name(raw, "application", None, replacement)
