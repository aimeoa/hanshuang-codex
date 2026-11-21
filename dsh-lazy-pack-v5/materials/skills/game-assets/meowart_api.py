#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from PIL import Image
except ImportError:  # Pillow is required only for strict texture validation.
    Image = None

MEOWART_API_CLI_VERSION = "2026.07.30.3"
DEFAULT_API_BASE = "https://api.meowa.ai"
DEFAULT_API_KEY_ENV = "MEOWART_API_KEY"
DEFAULT_DEV_KEY_ENV = "DEV_API_KEY"
_DEV_AUTH_PREFIX = "x-dev-key:"
DEFAULT_WORK_DIR = "./meowa-output"
DEFAULT_TIMEOUT = 240
DEFAULT_MAX_WAIT = 900
DEFAULT_POLL_INTERVAL = 3.0
ACTIVE_JOB_STATUSES = {"queued", "pending", "running"}
TERMINAL_JOB_STATUSES = {"success", "failure", "cancelled"}
TERMINAL_ANIMATE_STATUSES = {"success", "completed", "failure", "failed", "cancelled", "canceled"}
SUCCESS_ANIMATE_STATUSES = {"success", "completed"}
LONG_INLINE_DATA_DISPLAY_LIMIT = 240
AUTH_HEADER_HOST = "api.meowa.ai"
MEOWART_ENDPOINT_HINT = (
    "Meowa does not expose /generate or /api/generate. "
    "Use POST /api/pixel-gen for pixel sprites, POST /api/hd-gen for HD assets, "
    "or a documented workflow command for specialized assets."
)
GENERAL_IMAGE_ENDPOINT = "/api/gemini/jobs"
NANO_BANANA_MODEL = "gemini-3.1-flash-image"
IMAGE_2_MODEL = "gpt-image-2"
VIDEO_MOTION_MODE_TO_MODEL = {
    "controlled": "doubao-seedance-1-5-pro-251215",
    "complex": "doubao-seedance-2-0-mini-260615",
}
MAP_PRESET_CATALOG_MAX_BYTES = 10 * 1024 * 1024
TEXTURE_REFERENCE_CATALOG_MAX_BYTES = 2 * 1024 * 1024
STANDARD_TEXTURE_SIZE = 64
PIXEL_GENERAL_WORKFLOW_ID = "pixel_gen_general"
PIXEL_UNIVERSAL_TEMPLATE_NAME = "xlarge_4_3"
MAP_REFERENCE_TYPE_TO_WORKFLOW = {
    "pixel-isometric": "pixel_isometric_gen",
    "pixel-hex-isometric": "pixel_hex_isometric_gen",
    "hd-isometric": "hd_isometric_gen",
    "hd-hex-isometric": "hd_hex_isometric_gen",
    "tileset": "tileset_gen",
}
MAP_REFERENCE_TYPE_LABELS = {
    "pixel-isometric": "Pixel Isometric",
    "pixel-hex-isometric": "Pixel Hex Isometric",
    "hd-isometric": "HD Isometric",
    "hd-hex-isometric": "HD Hex Isometric",
    "tileset": "Tileset",
}
MAP_REFERENCE_LAYOUT_GROUPS = {
    "pixel-isometric": {
        "single": "pixel_64",
        "2x2": "pixel_128_32",
    },
    "pixel-hex-isometric": {
        "single": "pixel_single",
        "2x2": "pixel_tetraploid",
        "7-cell": "pixel_heptaploid",
        "template": "workflow_template",
    },
    "hd-isometric": {
        "single": "hd_single",
        "2x2": "hd_tetraploid",
    },
    "hd-hex-isometric": {
        "single": "hd_single",
        "2x2": "hd_tetraploid",
    },
    "tileset": {
        "template": "tileset_template",
    },
}
MAP_WORKFLOW_ENDPOINTS = {
    "pixel_isometric_gen": "/api/workflows/pixel_isometric_gen/run",
    "pixel_hex_isometric_gen": "/api/workflows/pixel_hex_isometric_gen/run",
    "hd_isometric_gen": "/api/workflows/hd_isometric_gen/run",
    "hd_hex_isometric_gen": "/api/workflows/hd_hex_isometric_gen/run",
}
MAP_WORKFLOW_COMMANDS = {
    "isometric-gen-submit": "pixel_isometric_gen",
    "pixel-isometric-gen-submit": "pixel_isometric_gen",
    "isometric-gen-run": "pixel_isometric_gen",
    "pixel-isometric-gen-run": "pixel_isometric_gen",
    "isometric-gen-poll": "pixel_isometric_gen",
    "pixel-isometric-gen-poll": "pixel_isometric_gen",
    "hex-isometric-gen-submit": "pixel_hex_isometric_gen",
    "pixel-hex-isometric-gen-submit": "pixel_hex_isometric_gen",
    "hex-isometric-gen-run": "pixel_hex_isometric_gen",
    "pixel-hex-isometric-gen-run": "pixel_hex_isometric_gen",
    "hex-isometric-gen-poll": "pixel_hex_isometric_gen",
    "pixel-hex-isometric-gen-poll": "pixel_hex_isometric_gen",
    "hd-isometric-gen-submit": "hd_isometric_gen",
    "hd-isometric-gen-run": "hd_isometric_gen",
    "hd-isometric-gen-poll": "hd_isometric_gen",
    "hd-hex-isometric-gen-submit": "hd_hex_isometric_gen",
    "hd-hex-isometric-gen-run": "hd_hex_isometric_gen",
    "hd-hex-isometric-gen-poll": "hd_hex_isometric_gen",
}
MAP_WORKFLOW_POLL_COMMANDS = {
    command for command in MAP_WORKFLOW_COMMANDS if command.endswith("-poll")
}
CHARACTER_MULTI_VIEW_ENDPOINT = "/api/workflows/character_multi_view_generator/run"
CHARACTER_MULTI_VIEW_SUBMIT_COMMANDS = {
    "character-multi-view-submit",
    "character-8-direction-submit",
    "character-eight-direction-submit",
}
CHARACTER_MULTI_VIEW_RUN_COMMANDS = {
    "character-multi-view-run",
    "character-8-direction-run",
    "character-eight-direction-run",
}
CHARACTER_MULTI_VIEW_POLL_COMMANDS = {
    "character-multi-view-poll",
    "character-8-direction-poll",
    "character-eight-direction-poll",
}
UI_GEN_ENDPOINT = "/api/workflows/general_ui_gen/run"
UI_GEN_SUBMIT_COMMANDS = {
    "ui-gen-submit",
    "general-ui-gen-submit",
}
UI_GEN_RUN_COMMANDS = {
    "ui-gen-run",
    "general-ui-gen-run",
}
UI_GEN_POLL_COMMANDS = {
    "ui-gen-poll",
    "general-ui-gen-poll",
}
ONE_CLICK_UPGRADE_ENDPOINT = "/api/workflows/one_click_upgrade/run"
ONE_CLICK_UPGRADE_PROMPTS_ENDPOINT = "/api/workflows/one_click_upgrade/prompts"
PROMPT_ONLY_MAX_ATTEMPTS = 3
PROMPT_ONLY_RETRY_DELAY_SECONDS = 5


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(line_buffering=True)


def _mime_for_path(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _endpoint_hint_for_response(response: requests.Response) -> str:
    path = urlparse(str(response.url)).path.rstrip("/").lower()
    if response.status_code == 404 and path in {"/generate", "/api/generate"}:
        return f" {MEOWART_ENDPOINT_HINT}"
    return ""


def _parse_json_response(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        body = response.text[:500].strip()
        raise ValueError(
            f"expected JSON response, got {content_type or 'unknown'}: {body}"
            f"{_endpoint_hint_for_response(response)}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object, got {type(payload).__name__}")
    return payload


def _request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    timeout: int,
    verify: bool,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | list[tuple[str, Any]] | None = None,
    files: dict[str, tuple[str, bytes, str]] | list[tuple[str, tuple[str, bytes, str]]] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[requests.Response, dict[str, Any]]:
    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        data=data,
        files=files,
        json=json_body,
        timeout=timeout,
        verify=verify,
    )
    try:
        return response, _parse_json_response(response)
    except ValueError as exc:
        hint = _endpoint_hint_for_response(response)
        if hint and hint not in str(exc):
            raise ValueError(f"{exc}{hint}") from exc
        raise


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_json_for_display(payload: Any) -> str:
    display_payload = _sanitize_response_for_local_storage(payload)
    return json.dumps(display_payload, ensure_ascii=False, indent=2)


def _format_public_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _video_model_name(motion_mode: str) -> str:
    normalized = str(motion_mode or "controlled").strip().lower() or "controlled"
    try:
        return VIDEO_MOTION_MODE_TO_MODEL[normalized]
    except KeyError as exc:
        supported = ", ".join(VIDEO_MOTION_MODE_TO_MODEL)
        raise ValueError(f"motion_mode must be one of: {supported}") from exc


def _map_preset_catalog_endpoint(api_base: str) -> str:
    return _normalize_base_url(api_base, "/api/agent-skills/game-assets/map-presets")


def fetch_map_preset_catalog(
    *,
    api_base: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _map_preset_catalog_endpoint(api_base)
    response, payload = _request_json(
        method="GET",
        url=url,
        headers={"Accept": "application/json"},
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    if len(response.content) > MAP_PRESET_CATALOG_MAX_BYTES:
        raise RuntimeError(f"map preset catalog too large: {len(response.content)} bytes")
    presets = payload.get("presets")
    if not isinstance(presets, list):
        raise ValueError("map preset catalog response missing presets list")
    return payload


def _texture_reference_catalog_endpoint(api_base: str) -> str:
    return _normalize_base_url(api_base, "/api/workflows/texture_gen")


def _texture_reference_id(item: dict[str, Any]) -> str:
    item_path = str(item.get("path") or "").strip()
    return f"texture-{hashlib.sha256(item_path.encode('utf-8')).hexdigest()[:16]}"


def fetch_texture_reference_catalog(
    *,
    api_base: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    response, payload = _request_json(
        method="GET",
        url=_texture_reference_catalog_endpoint(api_base),
        headers={"Accept": "application/json"},
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    if len(response.content) > TEXTURE_REFERENCE_CATALOG_MAX_BYTES:
        raise RuntimeError(f"texture reference catalog too large: {len(response.content)} bytes")

    templates = payload.get("templates")
    if not isinstance(templates, list):
        raise ValueError("texture reference catalog response missing templates list")
    default_template = next(
        (
            template
            for template in templates
            if isinstance(template, dict) and str(template.get("template_id") or "") == "default"
        ),
        None,
    )
    if not isinstance(default_template, dict):
        raise ValueError("texture reference catalog response missing the public 64px template")
    catalog = (default_template.get("params") or {}).get("texture_catalog")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise ValueError("texture reference catalog response missing items list")
    return catalog


def _texture_reference_text_blob(item: dict[str, Any]) -> str:
    values: list[Any] = [
        item.get("name"),
        item.get("name_en"),
        item.get("name_zh"),
        item.get("category"),
        item.get("category_zh"),
        *(item.get("color_tags") or []),
        *(item.get("color_tags_zh") or []),
    ]
    return " ".join(str(value) for value in values if value).lower()


def _public_texture_reference(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "reference_id": _texture_reference_id(item),
        "name": str(item.get("name") or ""),
        "category": str(item.get("category") or ""),
        "dimensions": f"{STANDARD_TEXTURE_SIZE}x{STANDARD_TEXTURE_SIZE}",
    }
    for source_key, public_key in (
        ("name_en", "name_en"),
        ("name_zh", "name_zh"),
        ("category_zh", "category_zh"),
        ("color_tags", "color_tags"),
        ("color_tags_zh", "color_tags_zh"),
    ):
        value = item.get(source_key)
        if value:
            result[public_key] = value
    return result


def _search_texture_reference_catalog(
    catalog: dict[str, Any],
    *,
    query: str = "",
    category: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    normalized_category = str(category or "").strip()
    tokens = _query_tokens(query)
    candidates = [
        item
        for item in catalog.get("items") or []
        if isinstance(item, dict)
        and (not normalized_category or str(item.get("category") or "") == normalized_category)
    ]
    matches = [
        item
        for item in candidates
        if not tokens or all(token in _texture_reference_text_blob(item) for token in tokens)
    ]
    match_mode = "all"
    if tokens and not matches:
        matches = [
            item
            for item in candidates
            if any(token in _texture_reference_text_blob(item) for token in tokens)
        ]
        match_mode = "any-fallback"
    capped_limit = max(int(limit or 20), 1)
    return {
        "texture_size": STANDARD_TEXTURE_SIZE,
        "dimensions": f"{STANDARD_TEXTURE_SIZE}x{STANDARD_TEXTURE_SIZE}",
        "query": query,
        "category": normalized_category,
        "match_mode": match_mode,
        "count": len(matches),
        "matches": [_public_texture_reference(item) for item in matches[:capped_limit]],
    }


def search_texture_references(
    *,
    api_base: str,
    query: str = "",
    category: str = "",
    limit: int = 20,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    catalog = fetch_texture_reference_catalog(api_base=api_base, timeout=timeout, verify=verify)
    return _search_texture_reference_catalog(
        catalog,
        query=query,
        category=category,
        limit=limit,
    )


def public_texture_reference_categories(catalog: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, dict[str, Any]] = {}
    for item in catalog.get("items") or []:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        if not category:
            continue
        bucket = counts.setdefault(
            category,
            {
                "category": category,
                "category_zh": str(item.get("category_zh") or ""),
                "count": 0,
            },
        )
        bucket["count"] += 1
    return {
        "texture_size": STANDARD_TEXTURE_SIZE,
        "dimensions": f"{STANDARD_TEXTURE_SIZE}x{STANDARD_TEXTURE_SIZE}",
        "count": sum(item["count"] for item in counts.values()),
        "categories": [counts[key] for key in sorted(counts)],
    }


def _require_standard_texture(path: Path, *, label: str) -> None:
    if Image is None:
        raise RuntimeError("Pillow is required for texture validation; run: python3 -m pip install Pillow")
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except Exception as exc:
        raise ValueError(f"{label} must be a valid image: {path}") from exc
    if (width, height) != (STANDARD_TEXTURE_SIZE, STANDARD_TEXTURE_SIZE):
        raise ValueError(
            f"{label} must be exactly {STANDARD_TEXTURE_SIZE}x{STANDARD_TEXTURE_SIZE} pixels; "
            f"got {width}x{height}: {path}"
        )


def download_texture_references(
    *,
    api_base: str,
    reference_ids: list[str] | None = None,
    query: str = "",
    category: str = "",
    limit: int = 20,
    output_dir: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = fetch_texture_reference_catalog(api_base=api_base, timeout=timeout, verify=verify)
    items = [item for item in catalog.get("items") or [] if isinstance(item, dict)]
    wanted = {str(item).strip() for item in reference_ids or [] if str(item).strip()}
    if wanted:
        selected = [item for item in items if _texture_reference_id(item) in wanted]
        unknown = wanted - {_texture_reference_id(item) for item in selected}
        if unknown:
            raise ValueError(f"unknown texture reference id: {', '.join(sorted(unknown))}")
        public_search = {
            "texture_size": STANDARD_TEXTURE_SIZE,
            "dimensions": f"{STANDARD_TEXTURE_SIZE}x{STANDARD_TEXTURE_SIZE}",
            "count": len(selected),
            "matches": [_public_texture_reference(item) for item in selected],
        }
    else:
        search_payload = _search_texture_reference_catalog(
            catalog,
            query=query,
            category=category,
            limit=limit,
        )
        selected_ids = {item["reference_id"] for item in search_payload["matches"]}
        selected = [item for item in items if _texture_reference_id(item) in selected_ids]
        public_search = search_payload
    if not selected:
        raise RuntimeError("no 64x64 texture reference matched the requested filters")

    target_dir = Path(output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = target_dir / "texture_reference_search.json"
    _save_json(manifest_path, public_search)
    downloads: list[dict[str, Any]] = [{"type": "json", "path": str(manifest_path)}]
    for index, item in enumerate(selected[: max(int(limit or len(selected)), 1)], start=1):
        source_url = str(item.get("preview_url") or "").strip()
        if not source_url.startswith("https://"):
            raise ValueError(f"texture reference has no secure download URL: {_texture_reference_id(item)}")
        filename = Path(str(item.get("path") or "texture.png")).name
        target_path = target_dir / f"{index:02d}_{_safe_slug(str(item.get('name') or Path(filename).stem))}.png"
        mime_type = _download_file(
            source_url,
            target_path,
            timeout=timeout,
            verify=verify,
            require_media=True,
        )
        try:
            _require_standard_texture(target_path, label="downloaded texture reference")
        except Exception:
            target_path.unlink(missing_ok=True)
            raise
        downloads.append(
            {
                "type": "texture_reference",
                "reference_id": _texture_reference_id(item),
                "mime_type": mime_type,
                "path": str(target_path),
            }
        )
        print(f"[INFO] downloaded={target_path}")
    return public_search, downloads


def _preset_text_blob(preset: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "id",
        "catalogId",
        "workflowId",
        "workflowName",
        "templateId",
        "templateName",
        "templateDescription",
        "group",
        "filename",
        "label",
        "tileSize",
        "assetKind",
    ):
        value = preset.get(key)
        if value:
            parts.append(str(value))
    for value in preset.get("tags") or []:
        parts.append(str(value))
    metadata = preset.get("metadata")
    if isinstance(metadata, dict):
        for value in metadata.values():
            if value:
                parts.append(str(value))
    return " ".join(parts).lower()


def _query_tokens(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    return [token for token in normalized.split(" ") if token]


def _map_reference_type_for_workflow(workflow_id: str) -> str:
    normalized = str(workflow_id or "").strip()
    for map_type, candidate_workflow_id in MAP_REFERENCE_TYPE_TO_WORKFLOW.items():
        if normalized == candidate_workflow_id:
            return map_type
    return ""


def _resolve_map_reference_filters(
    *,
    map_type: str = "",
    theme: str = "",
    layout: str = "",
    group: str = "",
) -> tuple[str, str, str]:
    normalized_type = str(map_type or "").strip()
    normalized_theme = str(theme or "").strip()
    normalized_layout = str(layout or "").strip()
    normalized_group = str(group or "").strip()
    workflow_id = MAP_REFERENCE_TYPE_TO_WORKFLOW.get(normalized_type, "")
    if normalized_type and not workflow_id:
        available = ", ".join(MAP_REFERENCE_TYPE_TO_WORKFLOW)
        raise ValueError(f"unsupported map reference type: {normalized_type}; available: {available}")
    if normalized_layout:
        if not normalized_type:
            raise ValueError("--layout requires --type so its meaning is unambiguous")
        resolved_group = MAP_REFERENCE_LAYOUT_GROUPS.get(normalized_type, {}).get(normalized_layout, "")
        if not resolved_group:
            available = ", ".join(MAP_REFERENCE_LAYOUT_GROUPS.get(normalized_type, {}))
            raise ValueError(
                f"unsupported layout {normalized_layout!r} for {normalized_type}; available: {available}"
            )
        if normalized_group and normalized_group != resolved_group:
            raise ValueError(f"--layout {normalized_layout} conflicts with --group {normalized_group}")
        normalized_group = resolved_group
    return workflow_id, normalized_theme, normalized_group


def _preset_matches_filters(
    preset: dict[str, Any],
    *,
    workflow_id: str = "",
    template_id: str = "",
    tile_size: str = "",
    asset_kind: str = "",
    group: str = "",
) -> bool:
    filters = {
        "workflowId": workflow_id,
        "templateId": template_id,
        "tileSize": tile_size,
        "assetKind": asset_kind,
        "group": group,
    }
    for key, raw_expected in filters.items():
        expected = str(raw_expected or "").strip()
        if expected and str(preset.get(key) or "").strip() != expected:
            return False
    return True


def _preset_search_score(preset: dict[str, Any], tokens: list[str]) -> int:
    if not tokens:
        return 0
    score = 0
    weighted_fields = (
        ("templateId", 8),
        ("templateName", 6),
        ("group", 4),
        ("filename", 4),
        ("templateDescription", 3),
        ("label", 3),
    )
    for token in tokens:
        for key, weight in weighted_fields:
            if token in str(preset.get(key) or "").lower():
                score += weight
    return score


def search_map_presets(
    *,
    api_base: str,
    query: str = "",
    workflow_id: str = "",
    template_id: str = "",
    tile_size: str = "",
    asset_kind: str = "",
    group: str = "",
    limit: int = 20,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    catalog = fetch_map_preset_catalog(api_base=api_base, timeout=timeout, verify=verify)
    tokens = _query_tokens(query)
    candidates: list[tuple[dict[str, Any], str]] = []
    for preset in catalog.get("presets") or []:
        if not isinstance(preset, dict):
            continue
        if not _preset_matches_filters(
            preset,
            workflow_id=workflow_id,
            template_id=template_id,
            tile_size=tile_size,
            asset_kind=asset_kind,
            group=group,
        ):
            continue
        text_blob = _preset_text_blob(preset)
        candidates.append((preset, text_blob))

    match_mode = "all"
    selected = [item for item in candidates if not tokens or all(token in item[1] for token in tokens)]
    if tokens and not selected:
        selected = [item for item in candidates if any(token in item[1] for token in tokens)]
        match_mode = "any-fallback"

    matches: list[dict[str, Any]] = []
    for preset, _text_blob in selected:
        enriched = dict(preset)
        enriched["_score"] = _preset_search_score(enriched, tokens)
        matches.append(enriched)

    matches.sort(
        key=lambda item: (
            -int(item.get("_score") or 0),
            str(item.get("workflowId") or ""),
            str(item.get("templateId") or ""),
            str(item.get("group") or ""),
            str(item.get("filename") or ""),
        )
    )
    capped_limit = max(int(limit or 20), 1)
    return {
        "catalogId": catalog.get("catalogId"),
        "version": catalog.get("version"),
        "query": query,
        "filters": {
            "workflowId": workflow_id,
            "templateId": template_id,
            "tileSize": tile_size,
            "assetKind": asset_kind,
            "group": group,
        },
        "matchMode": match_mode,
        "count": len(matches),
        "matches": matches[:capped_limit],
    }


def public_map_reference_categories(catalog: dict[str, Any], *, map_type: str = "") -> dict[str, Any]:
    requested_type = str(map_type or "").strip()
    if requested_type and requested_type not in MAP_REFERENCE_TYPE_TO_WORKFLOW:
        available = ", ".join(MAP_REFERENCE_TYPE_TO_WORKFLOW)
        raise ValueError(f"unsupported map reference type: {requested_type}; available: {available}")

    type_buckets: dict[str, dict[str, Any]] = {}
    for raw_preset in catalog.get("presets") or []:
        if not isinstance(raw_preset, dict):
            continue
        current_type = str(raw_preset.get("catalogId") or "").strip()
        if current_type not in MAP_REFERENCE_TYPE_TO_WORKFLOW:
            current_type = _map_reference_type_for_workflow(str(raw_preset.get("workflowId") or ""))
        if not current_type or (requested_type and current_type != requested_type):
            continue
        bucket = type_buckets.setdefault(
            current_type,
            {
                "type": current_type,
                "name": MAP_REFERENCE_TYPE_LABELS[current_type],
                "count": 0,
                "layouts": {},
                "themes": {},
            },
        )
        bucket["count"] += 1

        raw_group = str(raw_preset.get("group") or "").strip()
        layout = next(
            (
                public_layout
                for public_layout, group_name in MAP_REFERENCE_LAYOUT_GROUPS.get(current_type, {}).items()
                if group_name == raw_group
            ),
            "",
        )
        if layout:
            layout_bucket = bucket["layouts"].setdefault(
                layout,
                {
                    "layout": layout,
                    "tile_size": str(raw_preset.get("tileSize") or ""),
                    "asset_kind": str(raw_preset.get("assetKind") or "reference"),
                    "count": 0,
                },
            )
            layout_bucket["count"] += 1

        theme = str(raw_preset.get("templateId") or "").strip()
        if theme:
            theme_bucket = bucket["themes"].setdefault(
                theme,
                {
                    "theme": theme,
                    "name": str(raw_preset.get("templateName") or theme),
                    "description": str(raw_preset.get("templateDescription") or ""),
                    "count": 0,
                },
            )
            theme_bucket["count"] += 1

    public_types: list[dict[str, Any]] = []
    for current_type in MAP_REFERENCE_TYPE_TO_WORKFLOW:
        bucket = type_buckets.get(current_type)
        if not bucket:
            continue
        public_types.append(
            {
                "type": bucket["type"],
                "name": bucket["name"],
                "count": bucket["count"],
                "layouts": [bucket["layouts"][key] for key in sorted(bucket["layouts"])],
                "themes": [bucket["themes"][key] for key in sorted(bucket["themes"])],
            }
        )
    return {
        "count": sum(item["count"] for item in public_types),
        "types": public_types,
    }


def _public_map_search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for raw_preset in payload.get("matches") or []:
        if not isinstance(raw_preset, dict):
            continue
        preset_id = str(raw_preset.get("id") or "").strip()
        if not preset_id:
            continue
        public_preset: dict[str, Any] = {
            "preset_id": preset_id,
            "name": str(
                raw_preset.get("label")
                or raw_preset.get("templateName")
                or Path(str(raw_preset.get("filename") or preset_id)).stem
            ),
        }
        map_type = str(raw_preset.get("catalogId") or "").strip()
        if map_type not in MAP_REFERENCE_TYPE_TO_WORKFLOW:
            map_type = _map_reference_type_for_workflow(str(raw_preset.get("workflowId") or ""))
        if map_type:
            public_preset["type"] = map_type
            theme = str(raw_preset.get("templateId") or "").strip()
            if theme:
                public_preset["theme"] = theme
        description = str(raw_preset.get("templateDescription") or "").strip()
        if description:
            public_preset["description"] = description
        for source_key, public_key in (
            ("group", "group"),
            ("tileSize", "tile_size"),
            ("assetKind", "asset_kind"),
        ):
            value = str(raw_preset.get(source_key) or "").strip()
            if value:
                public_preset[public_key] = value
        tags = [str(tag) for tag in raw_preset.get("tags") or [] if str(tag).strip()]
        if tags:
            public_preset["tags"] = tags
        matches.append(public_preset)

    public_filters: dict[str, Any] = {}
    filters = payload.get("filters")
    if isinstance(filters, dict):
        ids = [str(item) for item in filters.get("ids") or [] if str(item).strip()]
        if ids:
            public_filters["preset_ids"] = ids
        filter_type = _map_reference_type_for_workflow(str(filters.get("workflowId") or ""))
        if filter_type:
            public_filters["type"] = filter_type
            filter_theme = str(filters.get("templateId") or "").strip()
            if filter_theme:
                public_filters["theme"] = filter_theme
        for raw_key, public_key in (
            ("tileSize", "tile_size"),
            ("assetKind", "asset_kind"),
            ("group", "group"),
        ):
            value = str(filters.get(raw_key) or "").strip()
            if value:
                public_filters[public_key] = value

    public_payload = {
        "query": str(payload.get("query") or ""),
        "filters": public_filters,
        "count": int(payload.get("count") or len(matches)),
        "matches": matches,
    }
    match_mode = str(payload.get("matchMode") or "").strip()
    if match_mode:
        public_payload["match_mode"] = match_mode
    return public_payload


def _absolute_url(api_base: str, value: str) -> str:
    raw = str(value or "").strip()
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        return _normalize_base_url(api_base, raw)
    return raw


def _preset_download_filename(preset: dict[str, Any], index: int) -> str:
    filename = str(preset.get("filename") or "preset.png").strip() or "preset.png"
    suffix = Path(filename).suffix or ".png"
    stem = _safe_slug(
        "_".join(
            part
            for part in (
                str(preset.get("id") or ""),
                str(preset.get("label") or Path(filename).stem),
            )
            if part
        )
    )
    return f"{index:02d}_{stem}{suffix}"


def download_map_presets(
    *,
    api_base: str,
    query: str = "",
    preset_ids: list[str] | None = None,
    workflow_id: str = "",
    template_id: str = "",
    tile_size: str = "",
    asset_kind: str = "",
    group: str = "",
    limit: int = 20,
    output_dir: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if preset_ids:
        catalog = fetch_map_preset_catalog(api_base=api_base, timeout=timeout, verify=verify)
        wanted = {str(preset_id).strip() for preset_id in preset_ids if str(preset_id).strip()}
        matches = [
            preset for preset in catalog.get("presets") or []
            if isinstance(preset, dict) and str(preset.get("id") or "") in wanted
        ]
        search_payload = {
            "catalogId": catalog.get("catalogId"),
            "version": catalog.get("version"),
            "query": "",
            "filters": {"ids": sorted(wanted)},
            "count": len(matches),
            "matches": matches[: max(int(limit or len(matches) or 1), 1)],
        }
    else:
        search_payload = search_map_presets(
            api_base=api_base,
            query=query,
            workflow_id=workflow_id,
            template_id=template_id,
            tile_size=tile_size,
            asset_kind=asset_kind,
            group=group,
            limit=limit,
            timeout=timeout,
            verify=verify,
        )
        matches = list(search_payload.get("matches") or [])

    if not matches:
        raise RuntimeError("no map preset matched the requested filters")

    target_dir = Path(output_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    public_search_payload = _public_map_search_payload(search_payload)
    _save_json(target_dir / "map_preset_search.json", public_search_payload)

    downloads: list[dict[str, Any]] = [{"type": "json", "path": str(target_dir / "map_preset_search.json")}]
    for index, preset in enumerate(matches[: max(int(limit or len(matches)), 1)], start=1):
        if not isinstance(preset, dict):
            continue
        source_url = _absolute_url(
            api_base,
            str(preset.get("downloadPath") or preset.get("downloadUrl") or preset.get("url") or ""),
        )
        if not source_url:
            print(f"[WARN] preset has no downloadable URL: {preset.get('id')}", file=sys.stderr)
            continue
        target_path = target_dir / _preset_download_filename(preset, index)
        mime_type = _download_file(
            source_url,
            target_path,
            timeout=timeout,
            verify=verify,
            require_media=True,
        )
        downloads.append(
            {
                "type": "map_preset",
                "preset_id": preset.get("id"),
                "source_url": source_url,
                "mime_type": mime_type,
                "path": str(target_path),
            }
        )
        print(f"[INFO] downloaded={target_path}")
    return public_search_payload, downloads


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _mask_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    return "***REDACTED***"


def _sanitize_for_meta(value: Any, *, key: str = "") -> Any:
    lowered_key = key.lower()
    if isinstance(value, dict):
        return {inner_key: _sanitize_for_meta(inner_value, key=str(inner_key)) for inner_key, inner_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_meta(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_meta(item, key=key) for item in value]
    if isinstance(value, Path):
        return str(value)
    if any(token in lowered_key for token in {"api_key", "dev_key", "token", "authorization", "secret"}):
        return _mask_secret(str(value))
    if lowered_key == "data" and isinstance(value, str) and len(value) > LONG_INLINE_DATA_DISPLAY_LIMIT:
        return f"***TRUNCATED_INLINE_DATA:{len(value)} chars***"
    return value


def _create_run_dir(work_dir: str, command: str) -> Path:
    root = Path(work_dir).expanduser()
    return root / f"{_timestamp_slug()}_{_safe_slug(command)}"


def _resolve_output_dir(raw_path: str, run_dir: Path) -> Path:
    if str(raw_path or "").strip():
        return Path(raw_path).expanduser()
    return run_dir


def _predict_saved_dir(output_root: str | Path, slug_seed: str) -> Path:
    return Path(output_root).expanduser() / _safe_slug(slug_seed)


def _write_meta(
    *,
    run_dir: Path,
    started_at: str,
    finished_at: str,
    args: argparse.Namespace,
    request_payload: Any | None,
    response_payload: Any | None,
    downloads: list[dict[str, Any]] | None,
    effective_output_dir: str,
    error: str = "",
) -> None:
    # Intentionally do not persist requests, responses, credentials, or debug metadata.
    return None


def _suffix_from_mime(mime_type: str) -> str:
    normalized = str(mime_type or "").split(";", 1)[0].strip().lower()
    if not normalized:
        return ".bin"
    guessed = mimetypes.guess_extension(normalized)
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".bin"


def _download_file(
    url: str,
    target_path: Path,
    *,
    timeout: int,
    verify: bool,
    headers: dict[str, str] | None = None,
    require_media: bool = False,
) -> str:
    if urlparse(url).scheme.lower() != "https":
        raise ValueError("refusing non-HTTPS download")
    response = requests.get(url, timeout=timeout, verify=verify, headers=headers or None)
    response.raise_for_status()
    content_type = str(response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if require_media and not content_type.startswith(("image/", "audio/", "video/")):
        raise ValueError(f"refusing non-media download: content-type={content_type or 'missing'}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(response.content)
    return content_type


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_") or "output"
    encoded = cleaned.encode("utf-8")
    if len(encoded) <= 120:
        return cleaned
    digest = hashlib.sha256(encoded).hexdigest()[:8]
    prefix = cleaned
    while prefix and len(prefix.encode("utf-8")) > 110:
        prefix = prefix[:-1]
    return f"{prefix.rstrip('_')}_{digest}"


def _base_headers(api_key: str) -> dict[str, str]:
    token = str(api_key or "").strip()
    if token.startswith(_DEV_AUTH_PREFIX):
        return {"X-Dev-Key": token.removeprefix(_DEV_AUTH_PREFIX)}
    return {"Authorization": f"Bearer {token}"}


def _should_send_auth_headers(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme.lower() == "https" and (parsed.hostname or "").lower() == AUTH_HEADER_HOST


def _normalize_api_base(api_base: str) -> str:
    raw = str(api_base or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid Meowa service URL")
    if parsed.scheme != "https" or parsed.netloc.lower() != "api.meowa.ai":
        raise ValueError("the distributed Skill only connects to https://api.meowa.ai")

    path = parsed.path.rstrip("/")
    lowered_path = path.lower()
    if lowered_path in {"/generate", "/api/generate"}:
        print(
            f"[WARN] service URL included deprecated endpoint path {path!r}; using host root instead. "
            f"{MEOWART_ENDPOINT_HINT}",
            file=sys.stderr,
        )
        path = ""

    return parsed._replace(path=path, params="", query="", fragment="").geturl().rstrip("/")


def _normalize_base_url(api_base: str, endpoint: str) -> str:
    return f"{_normalize_api_base(api_base)}/{endpoint.lstrip('/')}"


def _print_status(prefix: str, payload: dict[str, Any]) -> None:
    status = str(payload.get("status") or "").strip()
    stage = str(payload.get("stage") or "").strip()
    error = _sanitize_diagnostic_text(payload.get("error"), limit=500)
    progress = payload.get("progress")
    progress_label = ""
    progress_percent = ""
    if isinstance(progress, dict):
        progress_label = str(progress.get("label") or "").strip()
        progress_percent = str(progress.get("percent") or "").strip()
    line = f"{prefix} status={status or '?'}"
    if stage:
        line += f" stage={stage}"
    if progress_label or progress_percent:
        line += f" progress={progress_label or '?'}:{progress_percent or '?'}%"
    if error:
        line += f" error={error}"
    print(line)


def _collect_http_urls(value: Any, *, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            found.extend(_collect_http_urls(inner, prefix=child_prefix))
        return found
    if isinstance(value, list):
        for index, inner in enumerate(value):
            child_prefix = f"{prefix}[{index}]"
            found.extend(_collect_http_urls(inner, prefix=child_prefix))
        return found
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            found.append((prefix or "url", raw))
    return found


def _suffix_from_url(url: str) -> str:
    path = Path(url.split("?", 1)[0])
    suffix = path.suffix.lower()
    return suffix if suffix else ".bin"


def _filename_from_url_or_key(url: str, key: str) -> str:
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name.strip()
    if raw_name and "." in raw_name and raw_name not in {".", ".."}:
        return raw_name
    fallback = _safe_slug(key.replace(".", "_").replace("[", "_").replace("]", ""))
    return f"{fallback}{_suffix_from_url(url)}"


def _unique_target_path(output_dir: Path, filename: str) -> Path:
    candidate = output_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        alternative = output_dir / f"{stem}_{counter}{suffix}"
        if not alternative.exists():
            return alternative
        counter += 1


def _download_named_urls(
    *,
    urls: list[tuple[str, str]],
    output_dir: Path,
    timeout: int,
    verify: bool,
    headers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    downloads: list[dict[str, Any]] = []
    for key, url in urls:
        if url in seen:
            continue
        seen.add(url)
        target = _unique_target_path(output_dir, _filename_from_url_or_key(url, key))
        try:
            request_headers = headers if headers and _should_send_auth_headers(url) else None
            mime_type = _download_file(
                url,
                target,
                timeout=timeout,
                verify=verify,
                headers=request_headers,
                require_media=True,
            )
            if target.suffix == ".bin":
                resolved_suffix = _suffix_from_mime(mime_type)
                if resolved_suffix != ".bin":
                    renamed_target = _unique_target_path(output_dir, f"{target.stem}{resolved_suffix}")
                    target.rename(renamed_target)
                    target = renamed_target
            downloads.append({"type": "media", "key": key, "path": str(target), "mime_type": mime_type})
            print(f"[INFO] downloaded={target}")
        except (requests.RequestException, ValueError) as exc:
            print(f"[WARN] download failed for {url}: {exc}", file=sys.stderr)
    return downloads


_DOWNLOADABLE_MEDIA_EXTENSIONS = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".png",
    ".wav",
    ".webm",
    ".webp",
}
_WORKFLOW_FINAL_OUTPUT_FIELDS: dict[str, frozenset[str]] = {
    "animate": frozenset({"animated_gif_path", "animated_webp_path", "spritesheet_path", "output_url", "url"}),
    "character_multi_view_generator": frozenset({"sprite_pack_preview_path", "sprite_paths", "final_sprite_paths", "url"}),
    "elevenlabs_generator": frozenset({"audio_path", "audio_paths", "url"}),
    "frames_edit": frozenset({"animation_path", "sprite_sheet_path", "url"}),
    "general_ui_gen": frozenset({"output_path", "url"}),
    "gemini_image": frozenset({"url"}),
    "hd_gen": frozenset({"final_sprite", "final_sprite_paths", "sprite_pack_preview_path", "output_url", "url"}),
    "hd_gen_grid_2x2": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "hd_gen_grid_4x4": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "hd_hex_isometric_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "hd_isometric_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "hd_side_scrolling_map_gen": frozenset({"background_path", "foreground_path", "midground_path", "url"}),
    "image_edit": frozenset({"edited_path", "remove_bg_path", "url"}),
    "image_expander": frozenset({"assembled_preview_path", "image_paths", "images", "tile_paths", "url"}),
    "isometric_texture_gen": frozenset({"final_isometric_texture_path", "final_texture_path", "texture_path", "url"}),
    "isometric_tileset_gen": frozenset({"final_isometric_tileset_path", "final_tileset_path", "tileset_path", "url"}),
    "music_generator": frozenset({"audio_path", "audio_paths", "url"}),
    "one_click_upgrade": frozenset({"output_paths"}),
    "pixel_gen": frozenset({"final_sprite", "final_sprite_paths", "sprite_pack_preview_path", "output_url", "url"}),
    "pixel_gen_general": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_24px": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_2x2": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_48px": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_4x4": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_5x5": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_grid_8x8": frozenset({"final_sprite_paths", "sprite_pack_preview_path", "url"}),
    "pixel_gen_mask_single": frozenset({"final_sprite", "url"}),
    "pixel_gen_self_loop": frozenset({"output_path", "tiling_preview_path", "image_paths", "url"}),
    "pixel_hex_isometric_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "pixel_isometric_16_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "pixel_isometric_32_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "pixel_isometric_gen": frozenset({"final_tile_paths", "tile_pack_preview_path", "url"}),
    "pixelate": frozenset({"pixel_image_path", "output_url", "result_url", "url"}),
    "remove_background": frozenset({"remove_bg_path", "transparent_path", "output_url", "result_url", "url"}),
    "seedance_generator": frozenset({"raw_video_path", "video_paths", "url"}),
    "side_scrolling_map_gen": frozenset({"background_path", "foreground_path", "midground_path", "url"}),
    "texture_gen": frozenset({"final_texture_path", "texture_path", "tiling_preview_path", "url"}),
    "tileset_gen": frozenset({"final_tileset_path", "tileset_path", "url"}),
}
_WORKFLOW_FINAL_OUTPUT_CONTAINERS: dict[str, frozenset[str]] = {
    "animate": frozenset({"animation_assets"}),
    "gemini_image": frozenset({"images"}),
}
_ANIMATE_DOWNLOAD_FORMATS = frozenset({"webp", "gif", "png"})
_ANIMATE_DOWNLOAD_PATH_PATTERN = re.compile(
    r"^/api/animate/jobs/[^/]+/outputs/"
    r"(?P<output_format>webp|gif|png)/download$"
)
_FINAL_OUTPUT_FIELDS = frozenset().union(*_WORKFLOW_FINAL_OUTPUT_FIELDS.values())
_BLOCKED_OUTPUT_KEY_PARTS = {
    "base_texture_path",
    "debug",
    "filled_reference_grid_path",
    "generated_grid_path",
    "generated_tileset_path",
    "generation_input_path",
    "generation_output_path",
    "gcs_run_prefix",
    "input_reference_paths",
    "manifest",
    "generation_config",
    "metadata",
    "params",
    "prepared_full_canvas_path",
    "prepared_reference_path",
    "prepared_reference_paths",
    "raw_generated_path",
    "reference_spritesheet_path",
    "run_dir",
    "seamless_input_texture_path",
    "source_run_dir",
    "source_texture_path",
    "source_tileset_path",
    "stage2_grid_clean_path",
    "stage2_grid_nobg_defringe_mask_path",
    "stage2_grid_nobg_defringe_path",
    "stage2_grid_nobg_path",
    "stage2_grid_path",
    "steps_metadata_path",
    "template_grid_path",
    "template_path",
    "template_reference_path",
}
_BLOCKED_OUTPUT_KEY_TOKENS = {
    "debug",
    "input",
    "manifest",
    "mask",
    "metadata",
    "prepared",
    "provider",
    "reference",
    "model",
    "source",
    "stage",
    "template",
    "temperature",
    "workflow",
}


def _output_key_parts(key: str) -> list[str]:
    return [
        part
        for part in re.split(r"[.\[\]]+", str(key or "").strip().lower())
        if part and not part.isdigit()
    ]


def _payload_workflow_id(payload: dict[str, Any]) -> str:
    candidates: list[Any] = [payload.get("workflow_id")]
    for container_name in ("result", "output"):
        container = payload.get(container_name)
        if not isinstance(container, dict):
            continue
        candidates.append(container.get("workflow_id"))
    for candidate in candidates:
        workflow_id = str(candidate or "").strip()
        if workflow_id:
            return workflow_id
    return ""


def _is_declared_animate_download_url(
    key_parts: list[str],
    parsed_url: Any,
) -> bool:
    if (parsed_url.hostname or "").lower() != AUTH_HEADER_HOST:
        return False
    match = _ANIMATE_DOWNLOAD_PATH_PATTERN.fullmatch(parsed_url.path or "")
    if match is None:
        return False

    output_format = str(match.group("output_format") or "").strip()
    if output_format not in _ANIMATE_DOWNLOAD_FORMATS:
        return False

    if key_parts in (["output", "url"], ["result", "output", "url"]):
        return True
    if len(key_parts) not in {3, 4}:
        return False
    if key_parts[-3] != "output":
        return False
    if key_parts[-2] not in {"transparent_output_urls", "download_urls"}:
        return False
    return key_parts[-1] == output_format


def _looks_like_downloadable_output_url(key: str, url: str, *, workflow_id: str = "") -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False

    key_parts = _output_key_parts(key)
    if not key_parts or any(
        part in _BLOCKED_OUTPUT_KEY_PARTS
        or any(token in part for token in _BLOCKED_OUTPUT_KEY_TOKENS)
        for part in key_parts
    ):
        return False

    normalized_workflow_id = str(workflow_id or "").strip()
    allowed_fields = _WORKFLOW_FINAL_OUTPUT_FIELDS.get(normalized_workflow_id)
    if not allowed_fields:
        return False
    if normalized_workflow_id == "animate" and _is_declared_animate_download_url(key_parts, parsed):
        return True

    path = parsed.path or ""
    if path.endswith("/") or Path(path).suffix.lower() not in _DOWNLOADABLE_MEDIA_EXTENSIONS:
        return False
    allowed_containers = _WORKFLOW_FINAL_OUTPUT_CONTAINERS.get(normalized_workflow_id, frozenset())

    leaf = key_parts[-1]
    if leaf not in allowed_fields:
        return False

    if leaf == "url":
        return len(key_parts) >= 2 and key_parts[-2] in {
            "output",
            "result",
            *allowed_containers,
        }
    return True


_LOCAL_RESPONSE_OMIT = object()
_LOCAL_RESPONSE_INLINE_DATA_KEYS = {
    "b64_json",
    "base64",
    "bytes",
    "file_data",
    "filedata",
    "inline_data",
    "inlinedata",
}
_LOCAL_RESPONSE_FILE_EXTENSIONS = _DOWNLOADABLE_MEDIA_EXTENSIONS | {".json"}
_EMBEDDED_HTTP_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_EMBEDDED_INTERNAL_PATH_PATTERN = re.compile(r"/(?:app|tmp|home|var)/[^\s\"'<>]+")


def _sanitize_diagnostic_text(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _EMBEDDED_HTTP_URL_PATTERN.sub("<omitted-non-final-url>", text)
    text = _EMBEDDED_INTERNAL_PATH_PATTERN.sub("<omitted-internal-path>", text)
    return text[: max(1, int(limit))]


def _is_internal_response_key(key: str) -> bool:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return False
    if normalized in _LOCAL_RESPONSE_INLINE_DATA_KEYS:
        return True
    if normalized in _BLOCKED_OUTPUT_KEY_PARTS:
        return True
    return any(token in normalized for token in _BLOCKED_OUTPUT_KEY_TOKENS)


def _is_final_output_key_path(key_path: str, *, workflow_id: str) -> bool:
    return _looks_like_downloadable_output_url(
        key_path,
        "https://artifact-policy.invalid/final.png",
        workflow_id=workflow_id,
    )


def _sanitize_response_value_for_local_storage(
    value: Any,
    *,
    key_path: str,
    workflow_id: str,
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            lowered_key = key.lower()
            if any(token in lowered_key for token in {"api_key", "dev_key", "token", "authorization", "secret"}):
                sanitized[key] = "***REDACTED***"
                continue
            if lowered_key == "data" and isinstance(raw_value, str):
                continue
            if _is_internal_response_key(key):
                continue
            child_path = f"{key_path}.{key}" if key_path else key
            child = _sanitize_response_value_for_local_storage(
                raw_value,
                key_path=child_path,
                workflow_id=workflow_id,
            )
            if child is not _LOCAL_RESPONSE_OMIT:
                sanitized[key] = child
        return sanitized

    if isinstance(value, (list, tuple)):
        sanitized_items: list[Any] = []
        for index, item in enumerate(value):
            child = _sanitize_response_value_for_local_storage(
                item,
                key_path=f"{key_path}[{index}]",
                workflow_id=workflow_id,
            )
            if child is not _LOCAL_RESPONSE_OMIT:
                sanitized_items.append(child)
        return sanitized_items

    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str):
        return value

    normalized = value.strip()
    if not normalized:
        return value
    lowered_key = _output_key_parts(key_path)[-1] if _output_key_parts(key_path) else ""
    if lowered_key == "data" and len(normalized) > LONG_INLINE_DATA_DISPLAY_LIMIT:
        return _LOCAL_RESPONSE_OMIT
    if normalized.startswith("data:"):
        return _LOCAL_RESPONSE_OMIT
    if normalized.startswith(("http://", "https://")):
        if _looks_like_downloadable_output_url(key_path, normalized, workflow_id=workflow_id):
            return normalized
        return _LOCAL_RESPONSE_OMIT
    if Path(normalized).is_absolute():
        return _LOCAL_RESPONSE_OMIT

    suffix = Path(normalized.split("?", 1)[0]).suffix.lower()
    if suffix in _LOCAL_RESPONSE_FILE_EXTENSIONS:
        if suffix != ".json" and _is_final_output_key_path(key_path, workflow_id=workflow_id):
            return normalized
        return _LOCAL_RESPONSE_OMIT
    sanitized_text = _EMBEDDED_HTTP_URL_PATTERN.sub("<omitted-non-final-url>", value)
    return _EMBEDDED_INTERNAL_PATH_PATTERN.sub("<omitted-internal-path>", sanitized_text)


def _sanitize_response_for_local_storage(value: Any) -> Any:
    """Remove internal artifacts from response snapshots before they reach local disk."""
    if value is None:
        return None
    workflow_id = _payload_workflow_id(value) if isinstance(value, dict) else ""
    sanitized = _sanitize_response_value_for_local_storage(
        value,
        key_path="",
        workflow_id=workflow_id,
    )
    return {} if sanitized is _LOCAL_RESPONSE_OMIT else sanitized


def image_file_to_data_url(image_path: str) -> str:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {path}")
    mime = _mime_for_path(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def get_credits_balance(
    *,
    api_base: str,
    api_key: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/credits/balance")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def poll_job_until_done(
    *,
    jobs_url: str,
    api_key: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(max_wait, 1)
    headers = _base_headers(api_key)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        try:
            _, payload = _request_json(
                method="GET",
                url=jobs_url,
                headers=headers,
                timeout=timeout,
                verify=verify,
            )
        except (requests.RequestException, ValueError) as exc:
            print(f"[WARN] poll request failed: {exc}", file=sys.stderr)
            time.sleep(max(poll_interval, 0.1))
            continue

        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_JOB_STATUSES:
            final_payload = payload
            break
        if status not in ACTIVE_JOB_STATUSES:
            print(f"[WARN] unexpected intermediate status: {status}", file=sys.stderr)
        time.sleep(max(poll_interval, 0.1))

    if final_payload is None:
        raise TimeoutError(f"polling timed out after {max_wait}s")
    return final_payload


def _public_template_catalog(
    payload: dict[str, Any],
    *,
    workflow_id: str = "",
) -> dict[str, Any]:
    templates: list[dict[str, Any]] = []
    normalized_workflow_id = str(workflow_id or "").strip()
    for raw_template in payload.get("templates") or []:
        if not isinstance(raw_template, dict):
            continue
        if normalized_workflow_id and str(raw_template.get("workflow_id") or "").strip() != normalized_workflow_id:
            continue
        template_name = str(raw_template.get("template_name") or "").strip()
        if not template_name:
            continue
        public_template: dict[str, Any] = {
            "template_name": template_name,
            "display_name": str(raw_template.get("display_name") or template_name),
            "description": str(raw_template.get("description") or ""),
            "labels": [str(label) for label in raw_template.get("labels") or [] if str(label).strip()],
            "output_size": str(raw_template.get("output_size") or ""),
        }
        output_size_px = raw_template.get("output_size_px")
        if isinstance(output_size_px, int) and output_size_px > 0:
            public_template["output_size_px"] = output_size_px

        defaults = raw_template.get("default_params")
        if isinstance(defaults, dict):
            target_count = defaults.get("target_count")
            if isinstance(target_count, int) and target_count > 0:
                public_template["default_count"] = target_count
            resolution = str(defaults.get("resolution") or "").strip()
            if resolution:
                public_template["default_resolution"] = resolution
            aspect_ratio = str(defaults.get("aspect_ratio") or "").strip()
            if aspect_ratio:
                public_template["default_aspect_ratio"] = aspect_ratio
            remove_bg_method = str(defaults.get("remove_bg_method") or "").strip().lower()
            if normalized_workflow_id == PIXEL_GENERAL_WORKFLOW_ID:
                remove_bg_method = "none"
            if remove_bg_method in {"none", "standard", "advanced"}:
                public_template["default_background_removal"] = remove_bg_method

            if normalized_workflow_id == PIXEL_GENERAL_WORKFLOW_ID:
                output_aspect_ratio = str(
                    defaults.get("output_aspect_ratio") or defaults.get("aspect_ratio") or ""
                ).strip()
                output_size = str(raw_template.get("output_size") or "large").strip()
                ratio_label = output_aspect_ratio or "flexible"
                public_template["display_name"] = f"Large Pixel Canvas — {ratio_label} / {output_size}"
                public_template["description"] = (
                    f"A {ratio_label} large-pixel canvas for scenes, illustrations, characters, "
                    "buildings, and other game assets."
                )
                public_template["labels"] = ["pixel", "large", ratio_label, output_size]
                if output_aspect_ratio:
                    public_template["default_aspect_ratio"] = output_aspect_ratio

        directions = [str(direction) for direction in raw_template.get("directions") or [] if str(direction).strip()]
        if raw_template.get("supports_direction") and directions:
            public_template["directions"] = directions
            default_direction = str(raw_template.get("default_direction") or "").strip()
            if default_direction:
                public_template["default_direction"] = default_direction
        if raw_template.get("is_beta"):
            public_template["is_beta"] = True
        templates.append(public_template)
    return {"templates": templates}


def pixel_gen_template_info(
    *,
    api_base: str,
    api_key: str,
    workflow_id: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/pixel-gen/template-info")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return _public_template_catalog(payload, workflow_id=workflow_id)


def validate_pixel_general_template(
    *,
    api_base: str,
    api_key: str,
    template_name: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> None:
    catalog = pixel_gen_template_info(
        api_base=api_base,
        api_key=api_key,
        workflow_id=PIXEL_GENERAL_WORKFLOW_ID,
        timeout=timeout,
        verify=verify,
    )
    supported_names = {
        str(template.get("template_name") or "").strip()
        for template in catalog.get("templates") or []
        if isinstance(template, dict)
    }
    if template_name not in supported_names:
        raise ValueError(
            f"unsupported large-pixel preset: {template_name}. "
            "Run large-pixel-template-info to list the available presets."
        )


def submit_pixel_gen(
    *,
    api_base: str,
    api_key: str,
    template_name: str,
    requirement: str,
    template_config: dict[str, Any] | None = None,
    job_name: str = "",
    aspect_ratio: str = "1:1",
    reference_file: str = "",
    reference_files: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    submit_url = _normalize_base_url(api_base, "/api/pixel-gen")
    data: dict[str, str] = {
        "template_name": template_name,
        "template_config": json.dumps(template_config or {}, ensure_ascii=False),
        "requirement": requirement,
        "aspect_ratio": aspect_ratio,
    }
    if job_name:
        data["job_name"] = job_name
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None
    if str(reference_file or "").strip():
        path = Path(reference_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference file not found: {path}")
        files = [("reference_file", (path.name, path.read_bytes(), _mime_for_path(path)))]
    for raw_path in reference_files or []:
        if not str(raw_path or "").strip():
            continue
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference file not found: {path}")
        if files is None:
            files = []
        files.append(("reference_files", (path.name, path.read_bytes(), _mime_for_path(path))))

    response, payload = _request_json(
        method="POST",
        url=submit_url,
        headers=_base_headers(api_key),
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def poll_pixel_gen_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/pixel-gen/jobs")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        params={"id": api_job_id},
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def wait_pixel_gen_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(max_wait, 1)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        payload = poll_pixel_gen_job(
            api_base=api_base,
            api_key=api_key,
            api_job_id=api_job_id,
            timeout=timeout,
            verify=verify,
        )
        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_JOB_STATUSES:
            final_payload = payload
            break
        time.sleep(max(poll_interval, 0.1))
    if final_payload is None:
        raise TimeoutError(f"pixel-gen polling timed out after {max_wait}s")
    return final_payload


def run_pixel_gen(
    *,
    api_base: str,
    api_key: str,
    template_name: str,
    requirement: str,
    template_config: dict[str, Any] | None = None,
    job_name: str = "",
    aspect_ratio: str = "1:1",
    reference_file: str = "",
    reference_files: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_pixel_gen(
        api_base=api_base,
        api_key=api_key,
        template_name=template_name,
        requirement=requirement,
        template_config=template_config,
        job_name=job_name,
        aspect_ratio=aspect_ratio,
        reference_file=reference_file,
        reference_files=reference_files,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("api_job_id") or "").strip()
    if not api_job_id:
        raise RuntimeError("pixel-gen submit response missing api_job_id")
    print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_pixel_gen_job(
        api_base=api_base,
        api_key=api_key,
        api_job_id=api_job_id,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def pixel_gen_history(
    *,
    api_base: str,
    api_key: str,
    limit: int = 20,
    offset: int = 0,
    status: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/pixel-gen/history")
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        params=params,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def pixel_gen_cancel(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, f"/api/pixel-gen/jobs/{api_job_id}/cancel")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def pixel_gen_download(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    output_dir: str,
    output_index: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> Path:
    if output_index is None:
        url = _normalize_base_url(api_base, f"/api/pixel-gen/jobs/{api_job_id}/download")
    else:
        url = _normalize_base_url(api_base, f"/api/pixel-gen/jobs/{api_job_id}/outputs/{output_index}/download")
    target_dir = Path(output_dir).expanduser()
    suffix = ".png"
    if output_index is None:
        filename = f"{api_job_id}{suffix}"
    else:
        filename = f"{api_job_id}_output_{output_index}{suffix}"
    path = target_dir / filename
    _download_file(
        url,
        path,
        timeout=timeout,
        verify=verify,
        headers=_base_headers(api_key),
        require_media=True,
    )
    return path


def hd_gen_template_info(
    *,
    api_base: str,
    api_key: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/hd-gen/template-info")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return _public_template_catalog(payload)


def submit_hd_gen(
    *,
    api_base: str,
    api_key: str,
    template_name: str,
    requirement: str,
    template_config: dict[str, Any] | None = None,
    job_name: str = "",
    resolution: str = "",
    aspect_ratio: str = "1:1",
    quality_mode: str = "standard",
    remove_bg_method: str = "standard",
    reference_file: str = "",
    reference_files: list[str] | None = None,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    data: dict[str, str] = {
        "template_name": template_name,
        "template_config": json.dumps(template_config or {}, ensure_ascii=False),
        "requirement": requirement,
        "job_name": job_name,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "quality_mode": quality_mode,
        "remove_bg_method": remove_bg_method,
    }
    if project_id is not None:
        data["project_id"] = project_id
    if thread_id is not None:
        data["thread_id"] = thread_id

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if str(reference_file or "").strip():
        path = Path(reference_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference file not found: {path}")
        files.append(("reference_file", (path.name, path.read_bytes(), _mime_for_path(path))))
    for raw_path in reference_files or []:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference file not found: {path}")
        files.append(("reference_files", (path.name, path.read_bytes(), _mime_for_path(path))))

    url = _normalize_base_url(api_base, "/api/hd-gen")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def poll_hd_gen_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/hd-gen/jobs")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        params={"id": api_job_id},
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def wait_hd_gen_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(max_wait, 1)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        payload = poll_hd_gen_job(
            api_base=api_base,
            api_key=api_key,
            api_job_id=api_job_id,
            timeout=timeout,
            verify=verify,
        )
        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_JOB_STATUSES:
            final_payload = payload
            break
        time.sleep(max(poll_interval, 0.1))
    if final_payload is None:
        raise TimeoutError(f"hd-gen polling timed out after {max_wait}s")
    return final_payload


def run_hd_gen(
    *,
    api_base: str,
    api_key: str,
    template_name: str,
    requirement: str,
    template_config: dict[str, Any] | None = None,
    job_name: str = "",
    resolution: str = "",
    aspect_ratio: str = "1:1",
    quality_mode: str = "standard",
    remove_bg_method: str = "standard",
    reference_file: str = "",
    reference_files: list[str] | None = None,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_hd_gen(
        api_base=api_base,
        api_key=api_key,
        template_name=template_name,
        requirement=requirement,
        template_config=template_config,
        job_name=job_name,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        quality_mode=quality_mode,
        remove_bg_method=remove_bg_method,
        reference_file=reference_file,
        reference_files=reference_files,
        project_id=project_id,
        thread_id=thread_id,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("api_job_id") or submit_payload.get("job_id") or "").strip()
    if not api_job_id:
        raise RuntimeError("hd-gen submit response missing api_job_id")
    print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_hd_gen_job(
        api_base=api_base,
        api_key=api_key,
        api_job_id=api_job_id,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def hd_gen_history(
    *,
    api_base: str,
    api_key: str,
    limit: int = 20,
    offset: int = 0,
    status: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/hd-gen/history")
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        params=params,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def hd_gen_cancel(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, f"/api/hd-gen/jobs/{api_job_id}/cancel")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def hd_gen_download(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    output_dir: str,
    output_index: int | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> Path:
    if output_index is None:
        url = _normalize_base_url(api_base, f"/api/hd-gen/jobs/{api_job_id}/download")
        filename = f"{api_job_id}.png"
    else:
        url = _normalize_base_url(api_base, f"/api/hd-gen/jobs/{api_job_id}/outputs/{output_index}/download")
        filename = f"{api_job_id}_output_{output_index}.png"
    target_dir = Path(output_dir).expanduser()
    path = target_dir / filename
    mime_type = _download_file(
        url,
        path,
        timeout=timeout,
        verify=verify,
        headers=_base_headers(api_key),
        require_media=True,
    )
    resolved_suffix = _suffix_from_mime(mime_type)
    if resolved_suffix != ".bin" and path.suffix.lower() != resolved_suffix:
        renamed_path = _unique_target_path(target_dir, f"{path.stem}{resolved_suffix}")
        path.rename(renamed_path)
        path = renamed_path
    return path


def submit_animate(
    *,
    api_base: str,
    api_key: str,
    image_data_url: str,
    prompt: str = "",
    is_pixel: bool = False,
    output_frames: int = 8,
    output_format: str = "webp",
    animation_type: str = "other",
    remove_bg_method: str = "advanced",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, "/api/animate")
    payload: dict[str, Any] = {
        "image": image_data_url,
        "prompt": prompt,
        "is_pixel": is_pixel,
        "optimize_prompt": True,
        "output_frames": output_frames,
        "output_format": output_format,
        "animation_type": animation_type,
        "remove_bg_method": remove_bg_method,
        "matte_color": "#808080",
    }

    response, body = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        json_body=payload,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(json.dumps(body, ensure_ascii=False, indent=2))
    return body


def _parse_keyframe_file_specs(specs: list[str], *, total_frames: int) -> list[dict[str, Any]]:
    if len(specs) < 2:
        raise ValueError("keyframe animation requires at least two --keyframe values")
    if total_frames < 2 or total_frames % 2 != 0:
        raise ValueError("total_frames must be an even integer of at least 2")

    frames: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for raw_spec in specs:
        index_text, separator, path_text = str(raw_spec or "").partition("=")
        if not separator or not index_text.strip() or not path_text.strip():
            raise ValueError("each --keyframe must use INDEX=PATH")
        try:
            index = int(index_text.strip())
        except ValueError as exc:
            raise ValueError("keyframe index must be an integer") from exc
        if index < 0 or index >= total_frames:
            raise ValueError(f"keyframe index must be between 0 and {total_frames - 1}")
        if index in seen_indexes:
            raise ValueError("keyframe indexes must be unique")
        path = Path(path_text.strip()).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"keyframe image not found: {path}")
        seen_indexes.add(index)
        frames.append({"index": index, "image": image_file_to_data_url(str(path)), "strength": 1.0})
    if 0 not in seen_indexes:
        raise ValueError("keyframe 0 is required")
    return sorted(frames, key=lambda frame: int(frame["index"]))


def submit_keyframes(
    *,
    api_base: str,
    api_key: str,
    keyframe_specs: list[str],
    prompt: str,
    total_frames: int = 8,
    output_format: str = "webp",
    animation_type: str = "other",
    remove_bg_method: str = "advanced",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": str(prompt or "").strip(),
        "optimize_prompt": True,
        "frames": _parse_keyframe_file_specs(keyframe_specs, total_frames=total_frames),
        "total_frames": total_frames,
        "output_format": output_format,
        "animation_type": animation_type,
        "remove_bg_method": remove_bg_method,
    }
    response, body = _request_json(
        method="POST",
        url=_normalize_base_url(api_base, "/api/animate/keyframes"),
        headers=_base_headers(api_key),
        json_body=payload,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(json.dumps(body, ensure_ascii=False, indent=2))
    return body


def submit_remove_background(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    mode: str = "hd",
    quality: str = "standard",
    prompt: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(image_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image file not found: {path}")
    normalized_mode = str(mode or "hd").strip().lower()
    if normalized_mode not in {"pixel", "hd"}:
        raise ValueError("mode must be one of: pixel, hd")
    normalized_quality = str(quality or "standard").strip().lower()
    if normalized_quality not in {"standard", "advanced"}:
        raise ValueError("quality must be one of: standard, advanced")
    data = {
        "method": normalized_mode,
        "remove_bg_method": normalized_quality,
        "enable_perfect_pixel": "false" if normalized_quality == "advanced" else "true",
        "is_white_bg": "false" if prompt.strip() else "true",
        "prompt": prompt,
    }
    files = {"file": (path.name, path.read_bytes(), _mime_for_path(path))}
    url = _normalize_base_url(api_base, "/api/image/remove-background")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_remove_background(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    mode: str = "hd",
    quality: str = "standard",
    prompt: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_remove_background(
        api_base=api_base,
        api_key=api_key,
        image_file=image_file,
        mode=mode,
        quality=quality,
        prompt=prompt,
        timeout=timeout,
        verify=verify,
    )
    jobs_url = str(submit_payload.get("jobs_url") or "").strip()
    if not jobs_url:
        raise RuntimeError("remove-background submit response missing jobs_url")
    final_payload = poll_job_until_done(
        jobs_url=jobs_url,
        api_key=api_key,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_pixelate(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    pixel_size: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(image_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image file not found: {path}")
    data = {"pixel_size": pixel_size}
    files = {"file": (path.name, path.read_bytes(), _mime_for_path(path))}
    url = _normalize_base_url(api_base, "/api/image/pixelate")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_pixelate(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    pixel_size: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_pixelate(
        api_base=api_base,
        api_key=api_key,
        image_file=image_file,
        pixel_size=pixel_size,
        timeout=timeout,
        verify=verify,
    )
    jobs_url = str(submit_payload.get("jobs_url") or "").strip()
    if not jobs_url:
        raise RuntimeError("pixelate submit response missing jobs_url")
    final_payload = poll_job_until_done(
        jobs_url=jobs_url,
        api_key=api_key,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_pixel_gen_self_loop(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    job_name: str = "",
    resolution: str = "1K",
    mode: str = "basic",
    direction: str = "horizontal",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(image_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"image file not found: {path}")
    data = {
        "job_name": job_name,
        "resolution": resolution,
        "mode": mode,
        "direction": direction,
    }
    files = {"file": (path.name, path.read_bytes(), _mime_for_path(path))}
    url = _normalize_base_url(api_base, "/api/workflows/pixel_gen_self_loop/run")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_pixel_gen_self_loop(
    *,
    api_base: str,
    api_key: str,
    image_file: str,
    job_name: str = "",
    resolution: str = "1K",
    mode: str = "basic",
    direction: str = "horizontal",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_pixel_gen_self_loop(
        api_base=api_base,
        api_key=api_key,
        image_file=image_file,
        job_name=job_name,
        resolution=resolution,
        mode=mode,
        direction=direction,
        timeout=timeout,
        verify=verify,
    )
    jobs_url = str(submit_payload.get("jobs_url") or "").strip()
    if not jobs_url:
        raise RuntimeError("self-loop submit response missing jobs_url")
    final_payload = poll_job_until_done(
        jobs_url=jobs_url,
        api_key=api_key,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def wait_submitted_workflow_job(
    *,
    api_base: str,
    api_key: str,
    submit_payload: dict[str, Any],
    label: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> dict[str, Any]:
    jobs_url = str(submit_payload.get("jobs_url") or "").strip()
    if jobs_url:
        return poll_job_until_done(
            jobs_url=jobs_url,
            api_key=api_key,
            timeout=timeout,
            max_wait=max_wait,
            poll_interval=poll_interval,
            verify=verify,
        )

    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if not api_job_id:
        raise RuntimeError(f"{label} submit response missing job_id")
    deadline = time.time() + max(max_wait, 1)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        payload = poll_job(
            api_base=api_base,
            api_key=api_key,
            api_job_id=api_job_id,
            timeout=timeout,
            verify=verify,
        )
        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_JOB_STATUSES:
            final_payload = payload
            break
        time.sleep(max(poll_interval, 0.1))
    if final_payload is None:
        raise TimeoutError(f"{label} polling timed out after {max_wait}s")
    return final_payload


def _upload_part(path_value: str, *, label: str) -> tuple[str, bytes, str]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path.name, path.read_bytes(), _mime_for_path(path)


def _build_general_image_request_body(
    *,
    prompt: str,
    reference_images: list[str] | None = None,
) -> dict[str, Any]:
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("general image generation requires --prompt")
    references = [str(value or "").strip() for value in reference_images or [] if str(value or "").strip()]
    if len(references) > 8:
        raise ValueError("general image generation accepts at most 8 reference images")

    parts: list[dict[str, Any]] = [{"text": normalized_prompt}]
    for raw_path in references:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference image not found: {path}")
        mime_type = _mime_for_path(path)
        if not mime_type.startswith("image/"):
            raise ValueError(f"reference file is not an image: {path}")
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            }
        )
    return {"contents": [{"role": "user", "parts": parts}]}


def submit_general_image(
    *,
    api_base: str,
    api_key: str,
    capability: str,
    prompt: str,
    reference_images: list[str] | None = None,
    resolution: str = "1K",
    aspect_ratio: str = "1:1",
    quality: str = "standard",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    normalized_capability = str(capability or "").strip().lower()
    if normalized_capability not in {"nano-banana", "image-2"}:
        raise ValueError("capability must be nano-banana or image-2")

    quality_map = {"standard": "low", "detailed": "medium", "ultimate": "high"}
    normalized_quality = str(quality or "standard").strip().lower()
    if normalized_quality not in quality_map:
        raise ValueError("quality must be one of: standard, detailed, ultimate")

    request_body = _build_general_image_request_body(
        prompt=prompt,
        reference_images=reference_images,
    )
    is_nano_banana = normalized_capability == "nano-banana"
    payload = {
        "generationProvider": "nanobanana" if is_nano_banana else "image2",
        "model": NANO_BANANA_MODEL if is_nano_banana else IMAGE_2_MODEL,
        "image2Quality": "medium" if is_nano_banana else quality_map[normalized_quality],
        "resolution": resolution,
        "aspectRatio": aspect_ratio,
        "requestBody": request_body,
    }
    url = _normalize_base_url(api_base, GENERAL_IMAGE_ENDPOINT)
    response, response_payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        json_body=payload,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(response_payload))
    return response_payload


def run_general_image(
    *,
    api_base: str,
    api_key: str,
    capability: str,
    prompt: str,
    reference_images: list[str] | None = None,
    resolution: str = "1K",
    aspect_ratio: str = "1:1",
    quality: str = "standard",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_general_image(
        api_base=api_base,
        api_key=api_key,
        capability=capability,
        prompt=prompt,
        reference_images=reference_images,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        quality=quality,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("api_job_id") or submit_payload.get("job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label=capability,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_curated_workflow(
    *,
    api_base: str,
    api_key: str,
    endpoint: str,
    data: dict[str, str],
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, endpoint)
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def design_one_click_upgrade_prompts(
    *,
    api_base: str,
    api_key: str,
    reference_image: str,
    prompt: str = "",
    count: int = 1,
    language: str = "zh",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> list[str]:
    if count < 1 or count > 8:
        raise ValueError("count must be between 1 and 8")
    normalized_language = str(language or "zh").strip().lower()
    if normalized_language not in {"zh", "en"}:
        raise ValueError("language must be one of: zh, en")

    request_data = {
        "prompt": str(prompt or "").strip(),
        "count": str(count),
        "language": normalized_language,
    }
    request_files = {
        "reference_image": _upload_part(reference_image, label="reference image")
    }
    last_error: Exception | None = None

    for attempt in range(1, PROMPT_ONLY_MAX_ATTEMPTS + 1):
        try:
            response = requests.request(
                method="POST",
                url=_normalize_base_url(api_base, ONE_CLICK_UPGRADE_PROMPTS_ENDPOINT),
                headers=_base_headers(api_key),
                data=request_data,
                files=request_files,
                timeout=timeout,
                verify=verify,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            content_type = response.headers.get("content-type", "")
            if (
                response.status_code >= 400
                and response.status_code != 429
                and response.status_code < 500
            ):
                if "application/json" in content_type.lower():
                    try:
                        error_payload = response.json()
                    except (requests.RequestException, ValueError):
                        error_payload = {"detail": response.text[:500].strip()}
                else:
                    error_payload = {"detail": response.text[:500].strip()}
                raise RuntimeError(
                    json.dumps(error_payload, ensure_ascii=False, indent=2)
                )
            if "application/json" not in content_type.lower():
                body = response.text[:500].strip()
                last_error = ValueError(
                    f"expected JSON response, got {content_type or 'unknown'}: {body}"
                )
            else:
                try:
                    payload = response.json()
                except (requests.RequestException, ValueError) as exc:
                    last_error = exc
                else:
                    if response.status_code >= 400:
                        error = RuntimeError(
                            json.dumps(payload, ensure_ascii=False, indent=2)
                        )
                        last_error = error
                    elif not isinstance(payload, list):
                        last_error = ValueError(
                            f"expected JSON array, got {type(payload).__name__}"
                        )
                    else:
                        prompts = [str(item or "").strip() for item in payload]
                        if len(prompts) == count and all(prompts):
                            return prompts
                        last_error = ValueError(
                            f"expected exactly {count} non-empty upgrade prompts"
                        )

        if attempt < PROMPT_ONLY_MAX_ATTEMPTS:
            print(
                f"[WARN] prompt-only attempt {attempt}/{PROMPT_ONLY_MAX_ATTEMPTS} "
                f"failed; retrying in {PROMPT_ONLY_RETRY_DELAY_SECONDS}s",
                file=sys.stderr,
            )
            time.sleep(PROMPT_ONLY_RETRY_DELAY_SECONDS)

    if last_error is None:
        raise RuntimeError("prompt-only request failed")
    raise last_error


def run_curated_workflow(
    *,
    api_base: str,
    api_key: str,
    endpoint: str,
    label: str,
    data: dict[str, str],
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_curated_workflow(
        api_base=api_base,
        api_key=api_key,
        endpoint=endpoint,
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label=label,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_sound_effect_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str,
    duration: float = 2,
    loop: bool = False,
    sound_pack: bool = False,
    variants: bool = False,
    count: int = 4,
    language: str = "en",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    normalized_duration = float(duration)
    if normalized_duration != 0.5 and not (normalized_duration.is_integer() and 1 <= normalized_duration <= 10):
        raise ValueError("duration must be 0.5 or an integer from 1 to 10 seconds")
    normalized_count = int(count)
    if not 1 <= normalized_count <= 10:
        raise ValueError("count must be between 1 and 10")
    if sound_pack and variants:
        raise ValueError("choose either sound-pack or variants, not both")
    data: dict[str, str] = {
        "prompt": prompt,
        "duration": str(normalized_duration),
        "loop": "true" if loop else "false",
        "sound_pack": "true" if sound_pack else "false",
        "variants": "true" if variants else "false",
        "count": str(normalized_count),
        "language": language,
    }

    url = _normalize_base_url(api_base, "/api/workflows/elevenlabs_generator/run")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_sound_effect_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str,
    duration: float = 2,
    loop: bool = False,
    sound_pack: bool = False,
    variants: bool = False,
    count: int = 4,
    language: str = "en",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_sound_effect_generator(
        api_base=api_base,
        api_key=api_key,
        prompt=prompt,
        duration=duration,
        loop=loop,
        sound_pack=sound_pack,
        variants=variants,
        count=count,
        language=language,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label="sound",
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_texture_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    texture_names: list[str] | None = None,
    self_loop: bool = True,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    data: list[tuple[str, Any]] = [
        ("prompt", prompt),
        ("self_loop", "true" if self_loop else "false"),
    ]
    for name in texture_names or []:
        data.append(("texture_names", name))
    if project_id is not None:
        data.append(("project_id", project_id))
    if thread_id is not None:
        data.append(("thread_id", thread_id))

    url = _normalize_base_url(api_base, "/api/workflows/texture_gen/run")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_texture_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    texture_names: list[str] | None = None,
    self_loop: bool = True,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_texture_generator(
        api_base=api_base,
        api_key=api_key,
        prompt=prompt,
        texture_names=texture_names,
        self_loop=self_loop,
        project_id=project_id,
        thread_id=thread_id,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label="texture-gen",
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_tileset_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    terrain_mode: str = "dual",
    foreground_texture: str = "",
    background_texture: str = "",
    remove_bg_method: str = "standard",
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    normalized_terrain_mode = str(terrain_mode or "").strip().lower()
    if normalized_terrain_mode not in {"foreground", "background", "dual"}:
        raise ValueError("terrain_mode must be one of: foreground, background, dual")
    normalized_remove_bg_method = str(remove_bg_method or "").strip().lower()
    if normalized_remove_bg_method not in {"none", "standard", "advanced"}:
        raise ValueError("remove_bg_method must be one of: none, standard, advanced")
    has_foreground_texture = bool(str(foreground_texture or "").strip())
    has_background_texture = bool(str(background_texture or "").strip())
    expected_inputs = {
        "foreground": (True, False),
        "background": (False, True),
        "dual": (True, True),
    }[normalized_terrain_mode]
    if (has_foreground_texture, has_background_texture) != expected_inputs:
        requirements = {
            "foreground": "only --foreground-texture",
            "background": "only --background-texture",
            "dual": "both --foreground-texture and --background-texture",
        }
        raise ValueError(
            f"terrain_mode={normalized_terrain_mode} requires {requirements[normalized_terrain_mode]}"
        )
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if has_foreground_texture:
        path = Path(foreground_texture).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"foreground texture not found: {path}")
        _require_standard_texture(path, label="foreground texture")
        files.append(("foreground_texture", (path.name, path.read_bytes(), _mime_for_path(path))))
    if has_background_texture:
        path = Path(background_texture).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"background texture not found: {path}")
        _require_standard_texture(path, label="background texture")
        files.append(("background_texture", (path.name, path.read_bytes(), _mime_for_path(path))))
    single_terrain = normalized_terrain_mode != "dual"
    data: dict[str, str] = {
        "prompt": prompt,
        "tileset_template": "dual_grid_15",
        "tileset_mode": "dual-grid-15",
        "terrain_mode": "single" if single_terrain else "dual",
        "remove_bg_method": normalized_remove_bg_method if single_terrain else "none",
    }
    if normalized_terrain_mode == "foreground":
        data["single_terrain_region"] = "foreground"
    elif normalized_terrain_mode == "background":
        data["single_terrain_region"] = "background"
    if project_id is not None:
        data["project_id"] = project_id
    if thread_id is not None:
        data["thread_id"] = thread_id

    url = _normalize_base_url(api_base, "/api/workflows/tileset_gen/run")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_tileset_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    terrain_mode: str = "dual",
    foreground_texture: str = "",
    background_texture: str = "",
    remove_bg_method: str = "standard",
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_tileset_generator(
        api_base=api_base,
        api_key=api_key,
        prompt=prompt,
        terrain_mode=terrain_mode,
        foreground_texture=foreground_texture,
        background_texture=background_texture,
        remove_bg_method=remove_bg_method,
        project_id=project_id,
        thread_id=thread_id,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label="tileset-gen",
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def _normalize_character_multi_view_mode(mode: str) -> str:
    normalized = str(mode or "pixel").strip().lower() or "pixel"
    if normalized not in {"pixel", "hd"}:
        raise ValueError("mode must be one of: pixel, hd")
    return normalized


def _normalize_character_multi_view_canvas_resolution(canvas_resolution: str) -> str:
    normalized = str(canvas_resolution or "1K").strip().upper() or "1K"
    if normalized not in {"1K", "2K"}:
        raise ValueError("canvas_resolution must be 1K or 2K")
    return normalized


def _normalize_character_multi_view_output_size(output_size: int | None) -> int | None:
    if output_size is None:
        return None
    parsed = int(output_size)
    if parsed <= 0:
        raise ValueError("output_size must be greater than 0")
    return parsed


def submit_character_multi_view_generator(
    *,
    api_base: str,
    api_key: str,
    reference_image: str,
    mode: str = "pixel",
    canvas_resolution: str = "1K",
    direction_mode: str = "mirror",
    aspect_ratio: str = "",
    remove_bg_method: str = "standard",
    extra_constraint: str = "",
    output_size: int | None = None,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    path = Path(reference_image).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"reference image not found: {path}")

    normalized_mode = _normalize_character_multi_view_mode(mode)
    normalized_output_size = _normalize_character_multi_view_output_size(output_size)
    normalized_canvas_resolution = (
        "2K"
        if normalized_mode == "hd"
        else _normalize_character_multi_view_canvas_resolution(canvas_resolution)
    )
    data: dict[str, str] = {
        "pixel": "true" if normalized_mode == "pixel" else "false",
        "canvas_resolution": normalized_canvas_resolution,
        "direction_mode": direction_mode,
        "aspect_ratio": aspect_ratio,
        "remove_bg_method": remove_bg_method,
        "extra_constraint": extra_constraint,
    }
    if normalized_output_size is not None:
        data["output_size"] = str(normalized_output_size)
    if project_id is not None:
        data["project_id"] = project_id
    if thread_id is not None:
        data["thread_id"] = thread_id

    files = {"reference_image": (path.name, path.read_bytes(), _mime_for_path(path))}
    url = _normalize_base_url(api_base, CHARACTER_MULTI_VIEW_ENDPOINT)
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_character_multi_view_generator(
    *,
    api_base: str,
    api_key: str,
    reference_image: str,
    mode: str = "pixel",
    canvas_resolution: str = "1K",
    direction_mode: str = "mirror",
    aspect_ratio: str = "",
    remove_bg_method: str = "standard",
    extra_constraint: str = "",
    output_size: int | None = None,
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_character_multi_view_generator(
        api_base=api_base,
        api_key=api_key,
        reference_image=reference_image,
        mode=mode,
        canvas_resolution=canvas_resolution,
        direction_mode=direction_mode,
        aspect_ratio=aspect_ratio,
        remove_bg_method=remove_bg_method,
        extra_constraint=extra_constraint,
        output_size=output_size,
        project_id=project_id,
        thread_id=thread_id,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label="character-multi-view",
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def _append_reference_image_files(files: list[tuple[str, tuple[str, bytes, str]]], reference_images: list[str] | None) -> None:
    for raw_path in reference_images or []:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference image not found: {path}")
        files.append(("reference_images", (path.name, path.read_bytes(), _mime_for_path(path))))


def _append_ui_reference_files(files: list[tuple[str, tuple[str, bytes, str]]], reference_images: list[str] | None) -> None:
    paths = [str(raw_path or "").strip() for raw_path in reference_images or [] if str(raw_path or "").strip()]
    if len(paths) > 8:
        raise ValueError("UI generation accepts at most 8 reference images")
    for path_text in paths:
        path = Path(path_text).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference image not found: {path}")
        files.append(("reference_files", (path.name, path.read_bytes(), _mime_for_path(path))))


def _normalize_ui_generation_mode(generation_mode: str) -> str:
    normalized = str(generation_mode or "generate").strip().lower() or "generate"
    aliases = {"generate": "generate", "extract": "ui_extract", "ui_extract": "ui_extract"}
    if normalized not in aliases:
        raise ValueError("mode must be one of: generate, extract")
    return aliases[normalized]


def submit_ui_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str,
    reference_images: list[str] | None = None,
    resolution: str = "2K",
    aspect_ratio: str = "1:1",
    quality: str = "detailed",
    remove_bg_method: str = "standard",
    generation_mode: str = "generate",
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    normalized_generation_mode = _normalize_ui_generation_mode(generation_mode)
    quality_map = {"standard": "low", "detailed": "medium", "ultimate": "high"}
    normalized_quality = str(quality or "detailed").strip().lower()
    if normalized_quality not in quality_map:
        raise ValueError("quality must be one of: standard, detailed, ultimate")
    normalized_remove_bg_method = str(remove_bg_method or "standard").strip().lower()
    if normalized_remove_bg_method not in {"none", "standard", "advanced"}:
        raise ValueError("remove_bg_method must be one of: none, standard, advanced")
    data: dict[str, str] = {
        "prompt": prompt,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "image2_quality": quality_map[normalized_quality],
        "remove_background": "false" if normalized_remove_bg_method == "none" else "true",
        "remove_bg_method": normalized_remove_bg_method,
        "split_components": "true",
        "generation_mode": normalized_generation_mode,
    }

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    _append_ui_reference_files(files, reference_images)
    if normalized_generation_mode == "ui_extract" and not files:
        raise ValueError("ui_extract mode requires at least one --reference-image")

    url = _normalize_base_url(api_base, UI_GEN_ENDPOINT)
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_ui_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str,
    reference_images: list[str] | None = None,
    resolution: str = "2K",
    aspect_ratio: str = "1:1",
    quality: str = "detailed",
    remove_bg_method: str = "standard",
    generation_mode: str = "generate",
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_ui_generator(
        api_base=api_base,
        api_key=api_key,
        prompt=prompt,
        reference_images=reference_images,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        quality=quality,
        remove_bg_method=remove_bg_method,
        generation_mode=generation_mode,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label="ui-gen",
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_map_workflow(
    *,
    api_base: str,
    api_key: str,
    workflow_id: str,
    prompt: str,
    reference_images: list[str] | None = None,
    mode: str = "standard",
    remove_bg_method: str = "",
    template: str = "",
    style_name: str = "",
    style_description: str = "",
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    if workflow_id not in MAP_WORKFLOW_ENDPOINTS:
        raise ValueError(f"unsupported map workflow: {workflow_id}")

    data: dict[str, str] = {
        "prompt": prompt,
        "mode": mode,
    }
    if template:
        data["template"] = template
    if remove_bg_method:
        data["remove_bg_method"] = remove_bg_method
    for key, value in {
        "style_name": style_name,
        "style_description": style_description,
    }.items():
        if value not in (None, ""):
            data[key] = str(value)
    if project_id is not None:
        data["project_id"] = project_id
    if thread_id is not None:
        data["thread_id"] = thread_id

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    _append_reference_image_files(files, reference_images)

    url = _normalize_base_url(api_base, MAP_WORKFLOW_ENDPOINTS[workflow_id])
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_map_workflow(
    *,
    api_base: str,
    api_key: str,
    workflow_id: str,
    label: str = "map",
    prompt: str,
    reference_images: list[str] | None = None,
    mode: str = "standard",
    remove_bg_method: str = "",
    template: str = "",
    style_name: str = "",
    style_description: str = "",
    project_id: str | None = None,
    thread_id: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_map_workflow(
        api_base=api_base,
        api_key=api_key,
        workflow_id=workflow_id,
        prompt=prompt,
        reference_images=reference_images,
        mode=mode,
        remove_bg_method=remove_bg_method,
        template=template,
        style_name=style_name,
        style_description=style_description,
        project_id=project_id,
        thread_id=thread_id,
        timeout=timeout,
        verify=verify,
    )
    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if api_job_id:
        print(f"[INFO] submitted api_job_id={api_job_id}")
    final_payload = wait_submitted_workflow_job(
        api_base=api_base,
        api_key=api_key,
        submit_payload=submit_payload,
        label=label,
        timeout=timeout,
        max_wait=max_wait,
        poll_interval=poll_interval,
        verify=verify,
    )
    return submit_payload, final_payload


def submit_music_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    audio_generate: bool = False,
    demo: bool = False,
    reference_images: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    data: dict[str, str] = {
        "prompt": prompt,
        "audio_generate": "true" if audio_generate else "false",
        "demo": "true" if demo else "false",
    }
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for raw_path in reference_images or []:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference image not found: {path}")
        files.append(("reference_images", (path.name, path.read_bytes(), _mime_for_path(path))))

    url = _normalize_base_url(api_base, "/api/workflows/music_generator/run")
    response, payload = _request_json(
        method="POST",
        url=url,
        headers=_base_headers(api_key),
        data=data,
        files=files or None,
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def poll_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    url = _normalize_base_url(api_base, f"/api/jobs/{api_job_id}")
    response, payload = _request_json(
        method="GET",
        url=url,
        headers=_base_headers(api_key),
        timeout=timeout,
        verify=verify,
    )
    if response.status_code >= 400:
        raise RuntimeError(_format_json_for_display(payload))
    return payload


def run_music_generator(
    *,
    api_base: str,
    api_key: str,
    prompt: str = "",
    audio_generate: bool = False,
    demo: bool = False,
    reference_images: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submit_payload = submit_music_generator(
        api_base=api_base,
        api_key=api_key,
        prompt=prompt,
        audio_generate=audio_generate,
        demo=demo,
        reference_images=reference_images,
        timeout=timeout,
        verify=verify,
    )
    jobs_url = str(submit_payload.get("jobs_url") or "").strip()
    if jobs_url:
        final_payload = poll_job_until_done(
            jobs_url=jobs_url,
            api_key=api_key,
            timeout=timeout,
            max_wait=max_wait,
            poll_interval=poll_interval,
            verify=verify,
        )
        return submit_payload, final_payload

    api_job_id = str(submit_payload.get("job_id") or submit_payload.get("api_job_id") or "").strip()
    if not api_job_id:
        raise RuntimeError("music submit response missing job_id")
    deadline = time.time() + max(max_wait, 1)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        payload = poll_job(
            api_base=api_base,
            api_key=api_key,
            api_job_id=api_job_id,
            timeout=timeout,
            verify=verify,
        )
        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_JOB_STATUSES:
            final_payload = payload
            break
        time.sleep(max(poll_interval, 0.1))
    if final_payload is None:
        raise TimeoutError(f"music polling timed out after {max_wait}s")
    return submit_payload, final_payload


def poll_animate_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    verify: bool = True,
) -> dict[str, Any]:
    return poll_job(
        api_base=api_base,
        api_key=api_key,
        api_job_id=api_job_id,
        timeout=timeout,
        verify=verify,
    )


def wait_animate_job(
    *,
    api_base: str,
    api_key: str,
    api_job_id: str,
    timeout: int = DEFAULT_TIMEOUT,
    max_wait: int = DEFAULT_MAX_WAIT,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    verify: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(max_wait, 1)
    final_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        try:
            payload = poll_animate_job(
                api_base=api_base,
                api_key=api_key,
                api_job_id=api_job_id,
                timeout=timeout,
                verify=verify,
            )
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"[WARN] animate poll request failed: {exc}", file=sys.stderr)
            time.sleep(max(poll_interval, 0.1))
            continue
        _print_status("[INFO]", payload)
        status = str(payload.get("status") or "").strip().lower()
        if status in TERMINAL_ANIMATE_STATUSES:
            final_payload = payload
            break
        time.sleep(max(poll_interval, 0.1))
    if final_payload is None:
        raise TimeoutError(f"animate polling timed out after {max_wait}s")
    return final_payload


def _save_run_outputs(
    *,
    output_root: str,
    slug_seed: str,
    submit_payload: dict[str, Any],
    final_payload: dict[str, Any],
    timeout: int,
    verify: bool,
    api_key: str = "",
    no_download: bool = False,
    workflow_id: str = "",
) -> tuple[Path, list[dict[str, Any]]]:
    output_dir = _predict_saved_dir(output_root, slug_seed)
    downloads: list[dict[str, Any]] = []
    normalized_workflow_id = str(workflow_id or _payload_workflow_id(final_payload)).strip()
    urls = [
        (key, url)
        for key, url in _collect_http_urls(final_payload)
        if _looks_like_downloadable_output_url(key, url, workflow_id=normalized_workflow_id)
    ]
    if not no_download and urls:
        print(f"[INFO] downloading_outputs count={len(urls)} to={output_dir}")
        headers = _base_headers(api_key) if api_key else None
        downloads.extend(_download_named_urls(
            urls=urls,
            output_dir=output_dir,
            timeout=timeout,
            verify=verify,
            headers=headers,
        ))
    final_outputs_path = output_dir / "final_outputs.json"
    manifest = {
        "status": str(final_payload.get("status") or "").strip(),
        "job_id": str(final_payload.get("api_job_id") or final_payload.get("job_id") or "").strip(),
        "outputs": [
            {
                "type": item.get("type"),
                "path": item.get("path"),
                "mime_type": item.get("mime_type"),
            }
            for item in downloads
        ],
    }
    _save_json(final_outputs_path, manifest)
    downloads.insert(0, {"type": "manifest", "path": str(final_outputs_path)})
    return output_dir, downloads


def _local_run_summary(
    *,
    submit_payload: dict[str, Any],
    final_payload: dict[str, Any],
    downloads: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": str(final_payload.get("status") or "").strip(),
        "job_id": str(
            final_payload.get("api_job_id")
            or final_payload.get("job_id")
            or submit_payload.get("api_job_id")
            or submit_payload.get("job_id")
            or ""
        ).strip(),
        "outputs": [
            {
                "type": item.get("type"),
                "path": item.get("path"),
                "mime_type": item.get("mime_type"),
            }
            for item in downloads
            if item.get("type") == "media"
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create production-ready game assets with Meowa.")
    parser.add_argument("--version", action="version", version=f"meowart_api.py {MEOWART_API_CLI_VERSION}")
    parser.add_argument(
        "--output-dir",
        "--output_dir",
        dest="output_dir",
        default="",
        help="Output root; the runner creates one task subdirectory",
    )
    parser.set_defaults(
        api_base=DEFAULT_API_BASE,
        api_key="",
        insecure=False,
        work_dir=DEFAULT_WORK_DIR,
        timeout=DEFAULT_TIMEOUT,
        max_wait=DEFAULT_MAX_WAIT,
        poll_interval=DEFAULT_POLL_INTERVAL,
        no_download=False,
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def option_exists(command_parser: argparse.ArgumentParser, *option_strings: str) -> bool:
        known_options = {
            option
            for action in command_parser._actions
            for option in getattr(action, "option_strings", ())
        }
        return any(option in known_options for option in option_strings)

    def add_if_missing(command_parser: argparse.ArgumentParser, *option_strings: str, **kwargs: Any) -> None:
        if not option_exists(command_parser, *option_strings):
            command_parser.add_argument(*option_strings, **kwargs)

    def add_shared_path_args(command_parser: argparse.ArgumentParser) -> None:
        add_if_missing(
            command_parser,
            "--output-dir",
            "--output_dir",
            dest="output_dir",
            default=argparse.SUPPRESS,
            help="Output root; the runner creates one task subdirectory",
        )

    def add_shared_runtime_args(command_parser: argparse.ArgumentParser) -> None:
        return None

    def add_map_preset_filter_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--type",
            dest="map_type",
            default="",
            choices=tuple(MAP_REFERENCE_TYPE_TO_WORKFLOW),
            help="Reference family; use --categories to see its themes and layouts",
        )
        command_parser.add_argument("--theme", default="", help="Exact theme from --categories, e.g. grassland or modern")
        command_parser.add_argument(
            "--layout",
            default="",
            choices=("single", "2x2", "7-cell", "template"),
            help="Friendly layout filter; requires --type",
        )
        command_parser.add_argument("--query", default="", help="Optional text refinement after type/theme/layout filters")
        command_parser.add_argument("--tile-size", default="", help="Optional tile size filter, e.g. 1x1, 2x2, 7-cell")
        command_parser.add_argument("--asset-kind", default="", help="Optional asset kind filter: reference or template")
        command_parser.add_argument("--group", default="", help="Advanced exact group filter; prefer --layout")
        command_parser.add_argument("--limit", type=int, default=20)
        command_parser.set_defaults(workflow_id="", template_id="")

    def add_map_workflow_args(
        command_parser: argparse.ArgumentParser,
        *,
        modes: tuple[str, ...],
        include_remove_bg: bool = False,
        include_template: bool = False,
    ) -> None:
        command_parser.add_argument("--prompt", required=True, help="Map tile requirement")
        command_parser.add_argument("--reference-image", action="append", default=[], help="Reference image; can be repeated")
        command_parser.add_argument("--mode", default="standard", choices=modes)
        if include_remove_bg:
            command_parser.add_argument(
                "--remove-bg-method",
                default="standard",
                choices=["none", "standard", "advanced"],
            )
        if include_template:
            command_parser.add_argument("--template", default="", help="Optional map preset")
        command_parser.set_defaults(
            project_id=None,
            thread_id=None,
        )

    map_preset_search = subparsers.add_parser("map-reference-search", aliases=["map-preset-search"], help="Browse or search reusable pixel and HD map references")
    add_map_preset_filter_args(map_preset_search)
    map_preset_search.add_argument(
        "--categories",
        action="store_true",
        help="List available types, themes, layouts, and counts; optionally narrow with --type",
    )

    map_preset_download = subparsers.add_parser("map-reference-download", aliases=["map-preset-download"], help="Download map references by preset id or structured filters")
    map_preset_download.add_argument(
        "--output-dir",
        "--output_dir",
        dest="output_dir",
        default=argparse.SUPPRESS,
        help="Directory that will receive the selected references",
    )
    add_map_preset_filter_args(map_preset_download)
    map_preset_download.add_argument("--preset-id", action="append", default=[], help="Preset id to download; can be repeated")

    texture_reference_search = subparsers.add_parser(
        "texture-reference-search",
        help="Search the public library of standard 64x64 texture references",
    )
    texture_reference_search.add_argument("--query", default="", help="Search texture names, categories, colors, and tags")
    texture_reference_search.add_argument("--category", default="", help="Exact category from --categories")
    texture_reference_search.add_argument("--limit", type=int, default=20)
    texture_reference_search.add_argument("--categories", action="store_true", help="List available 64x64 texture categories")

    texture_reference_download = subparsers.add_parser(
        "texture-reference-download",
        help="Download standard 64x64 texture references",
    )
    texture_reference_download.add_argument(
        "--output-dir",
        "--output_dir",
        dest="output_dir",
        default=argparse.SUPPRESS,
        help="Directory that will receive the selected 64x64 textures",
    )
    texture_reference_download.add_argument("--reference-id", action="append", default=[], help="Reference id to download; can be repeated")
    texture_reference_download.add_argument("--query", default="", help="Search texture names, categories, colors, and tags")
    texture_reference_download.add_argument("--category", default="", help="Exact category from texture-reference-search --categories")
    texture_reference_download.add_argument("--limit", type=int, default=20)

    nano_banana_run = subparsers.add_parser(
        "nano-banana-run",
        help="Create a general HD image with Nano Banana",
    )
    add_shared_path_args(nano_banana_run)
    nano_banana_run.add_argument("--prompt", required=True, help="Describe the requested image or asset sheet")
    nano_banana_run.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="Optional visual reference; repeat up to 8 times",
    )
    nano_banana_run.add_argument(
        "--resolution",
        default="1K",
        choices=["1K", "2K", "4K"],
        help="Canvas tier; recommended shared default is 1K",
    )
    nano_banana_run.add_argument(
        "--aspect-ratio",
        default="1:1",
        choices=["1:1", "3:4", "4:3", "2:3", "3:2", "4:5", "5:4", "9:16", "16:9", "21:9", "1:4", "4:1", "1:8", "8:1"],
        help="Canvas ratio; recommended shared default is 1:1",
    )

    image_2_run = subparsers.add_parser(
        "image-2-run",
        help="Create a general HD image with Image-2",
    )
    add_shared_path_args(image_2_run)
    image_2_run.add_argument("--prompt", required=True, help="Describe the requested image or asset sheet")
    image_2_run.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="Optional visual reference; repeat up to 8 times",
    )
    image_2_run.add_argument(
        "--resolution",
        default="1K",
        choices=["1K", "2K"],
        help="Canvas tier; recommended shared default is 1K",
    )
    image_2_run.add_argument(
        "--aspect-ratio",
        default="1:1",
        choices=["1:1", "3:4", "4:3", "9:16", "16:9"],
        help="Canvas ratio; recommended shared default is 1:1",
    )
    image_2_run.add_argument(
        "--quality",
        default="standard",
        choices=["standard", "detailed", "ultimate"],
        help=(
            "Output quality; default to Standard for inexpensive prompt testing, then "
            "rerun with Detailed after the prompt is approved"
        ),
    )

    image_edit_run = subparsers.add_parser("image-edit-run", help="Edit one or more game-art images")
    add_shared_path_args(image_edit_run)
    image_edit_run.add_argument("--reference-image", action="append", required=True, help="Input image; repeat up to 8 times")
    image_edit_run.add_argument("--prompt", required=True, help="Describe the requested edit")
    image_edit_run.add_argument("--mode", default="pixel", choices=["pixel", "hd"])
    image_edit_run.add_argument("--strict", action="store_true", help="Preserve exact pixel structure")
    image_edit_run.add_argument("--resolution", default="1K", choices=["1K", "2K"])
    image_edit_run.add_argument(
        "--aspect-ratio",
        default="auto",
        choices=["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "2:3", "3:2"],
    )
    image_edit_run.add_argument("--remove-bg-method", default="standard", choices=["none", "standard", "advanced"])

    animation_edit_run = subparsers.add_parser("animation-edit-run", help="Edit an animated GIF or WebP")
    add_shared_path_args(animation_edit_run)
    animation_edit_run.add_argument("--animation-file", required=True, help="Animated GIF or WebP input")
    animation_edit_run.add_argument("--reference-image", action="append", default=[], help="Optional visual reference; repeat up to 8 times")
    animation_edit_run.add_argument("--prompt", required=True, help="Describe the requested animation edit")
    animation_edit_run.add_argument("--mode", default="pixel", choices=["pixel", "hd"])
    animation_edit_run.add_argument("--remove-bg-method", default="advanced", choices=["none", "standard", "advanced"])

    one_click_prompts = subparsers.add_parser(
        "one-click-upgrade-prompts",
        help="Design a concise prompt list for consistent asset upgrades",
    )
    one_click_prompts.add_argument("--reference-image", required=True)
    one_click_prompts.add_argument("--prompt", default="", help="Optional overall upgrade direction")
    one_click_prompts.add_argument("--count", type=int, default=1, choices=range(1, 9))
    one_click_prompts.add_argument("--language", default="zh", choices=["zh", "en"])

    one_click_run = subparsers.add_parser(
        "one-click-upgrade-run",
        help="Create one to eight consistent upgrades or variants of an asset",
    )
    add_shared_path_args(one_click_run)
    one_click_run.add_argument("--reference-image", required=True)
    one_click_run.add_argument(
        "--variant-prompt",
        action="append",
        required=True,
        help="One concise prompt per output; repeat from one to eight times",
    )
    one_click_run.add_argument("--mode", default="pixel", choices=["pixel", "hd"])
    one_click_run.add_argument("--resolution", default="", choices=["1K", "2K"])
    one_click_run.add_argument("--remove-bg-method", default="none", choices=["none", "standard", "advanced"])

    video_prompt_list = subparsers.add_parser(
        "video-prompt-list",
        help="List recommended short-video action prompts",
    )
    add_shared_path_args(video_prompt_list)
    video_prompt_list.add_argument(
        "--motion-mode",
        default="controlled",
        choices=list(VIDEO_MOTION_MODE_TO_MODEL),
        help="Use controlled for first/last-frame control or complex for general motion",
    )

    video_run = subparsers.add_parser("video-run", help="Animate a still image into a short game clip")
    add_shared_path_args(video_run)
    video_run.add_argument("--first-frame", "--start-keyframe", dest="first_frame", required=True)
    video_run.add_argument("--last-frame", "--end-keyframe", dest="last_frame", default="")
    video_run.add_argument("--prompt", default="")
    video_run.add_argument("--action", default="")
    video_run.add_argument("--direction", default="")
    video_run.add_argument("--pixel", action="store_true", help="Preserve pixel-art motion")
    video_run.add_argument("--resolution", default="480p", choices=["480p", "720p"])
    video_run.add_argument("--frame-count", type=int, default=32, choices=[32, 40, 48])
    video_run.add_argument(
        "--motion-mode",
        default="controlled",
        choices=list(VIDEO_MOTION_MODE_TO_MODEL),
        help="Use controlled for first/last-frame control or complex for general motion",
    )
    video_run.add_argument(
        "--animation-type",
        default="other",
        choices=["idle", "walk", "run", "jump", "attack", "hit", "defeated", "other"],
    )

    isometric_texture_run = subparsers.add_parser("isometric-texture-run", help="Create a seamless isometric texture")
    add_shared_path_args(isometric_texture_run)
    isometric_texture_run.add_argument("--prompt", default="")
    isometric_texture_run.add_argument("--preset", default="")
    isometric_texture_run.add_argument("--texture-name", action="append", default=[])
    isometric_texture_run.add_argument("--reference-image", action="append", default=[])
    isometric_texture_run.add_argument("--self-loop", action="store_true", default=True)
    isometric_texture_run.add_argument("--no-self-loop", action="store_false", dest="self_loop")

    isometric_tileset_run = subparsers.add_parser("isometric-tileset-run", help="Create an isometric terrain tileset")
    add_shared_path_args(isometric_tileset_run)
    isometric_tileset_run.add_argument("--prompt", default="")
    isometric_tileset_run.add_argument("--terrain-mode", default="dual", choices=["dual", "single"])
    isometric_tileset_run.add_argument("--single-terrain-region", default="", choices=["", "foreground", "background"])
    isometric_tileset_run.add_argument("--show-base-color", action="store_true")
    isometric_tileset_run.add_argument("--remove-bg-method", default="standard", choices=["none", "standard", "advanced"])
    isometric_tileset_run.add_argument("--foreground-color", default="")
    isometric_tileset_run.add_argument("--background-color", default="")
    isometric_tileset_run.add_argument("--terrain-color", default="")
    isometric_tileset_run.add_argument("--foreground-texture", default="")
    isometric_tileset_run.add_argument("--background-texture", default="")

    side_map_run = subparsers.add_parser("side-scrolling-map-run", help="Create a layered pixel side-scrolling map")
    add_shared_path_args(side_map_run)
    side_map_run.add_argument("--midground", required=True)
    side_map_run.add_argument("--background", required=True)
    side_map_run.add_argument("--foreground", required=True)
    side_map_run.add_argument("--remove-bg-method", default="standard", choices=["standard", "advanced"])
    side_map_run.add_argument("--loop-midground", action="store_true", help="Make the midground loop horizontally")
    side_map_run.add_argument("--loop-background", action="store_true", help="Make the background loop horizontally")
    side_map_run.add_argument("--loop-foreground", action="store_true", help="Make the foreground loop horizontally")

    hd_side_map_run = subparsers.add_parser("hd-side-scrolling-map-run", help="Create a layered HD side-scrolling map")
    add_shared_path_args(hd_side_map_run)
    hd_side_map_run.add_argument("--midground", required=True)
    hd_side_map_run.add_argument("--background", required=True)
    hd_side_map_run.add_argument("--foreground", required=True)
    hd_side_map_run.add_argument(
        "--art-style",
        default="2d_hd",
        choices=["2d_hd", "2d_cartoon", "2d_ink", "clay", "low_poly_3d", "steampunk", "anime_hd"],
    )
    hd_side_map_run.add_argument("--custom-art-style", default="")
    hd_side_map_run.add_argument("--loop-midground", action="store_true", help="Make the midground loop horizontally")
    hd_side_map_run.add_argument("--loop-background", action="store_true", help="Make the background loop horizontally")
    hd_side_map_run.add_argument("--loop-foreground", action="store_true", help="Make the foreground loop horizontally")

    subparsers.add_parser("pixel-gen-template-info", help="List pixel-art presets")

    pixel_submit = subparsers.add_parser("pixel-gen-submit", help="Submit a pixel-gen job")
    add_shared_path_args(pixel_submit)
    pixel_submit.add_argument("--template-name", required=True)
    pixel_submit.add_argument("--requirement", required=True)
    pixel_submit.set_defaults(template_config="{}")
    pixel_submit.add_argument("--job-name", default="")
    pixel_submit.add_argument("--resolution", default="", help=argparse.SUPPRESS)
    pixel_submit.add_argument("--aspect-ratio", default="1:1")
    pixel_submit.add_argument("--reference-file", default="", help="Optional user reference image sent as reference_file")
    pixel_submit.add_argument("--reference-files", action="append", default=[], help="Optional user reference image; can be repeated")

    pixel_run = subparsers.add_parser("pixel-gen-run", help="Create pixel art from a preset")
    for action in pixel_submit._actions[1:]:
        if action.dest not in {"help", "job_name"}:
            pixel_run._add_action(action)
    pixel_run.set_defaults(job_name="")
    add_shared_runtime_args(pixel_run)

    subparsers.add_parser(
        "large-pixel-template-info",
        help="List large-pixel presets for scenes, illustrations, and other large assets",
    )

    large_pixel_run = subparsers.add_parser(
        "large-pixel-gen-run",
        help="Create a large pixel-art asset from a large-pixel preset",
    )
    add_shared_path_args(large_pixel_run)
    large_pixel_run.add_argument("--template-name", required=True, help="Preset from large-pixel-template-info")
    large_pixel_run.add_argument(
        "--prompt",
        "--requirement",
        dest="requirement",
        required=True,
        help="Describe the requested pixel-art asset",
    )
    large_pixel_run.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="Optional style or content reference; can be repeated",
    )
    large_pixel_run.add_argument(
        "--remove-bg-method",
        default="none",
        choices=["none", "standard"],
        help="Keep the composed background or remove a simple background",
    )

    pixel_universal_run = subparsers.add_parser(
        "pixel-universal-gen-run",
        help="Create a general-purpose 4:3 pixel scene, illustration, character, or design",
    )
    add_shared_path_args(pixel_universal_run)
    pixel_universal_run.add_argument(
        "--prompt",
        "--requirement",
        dest="requirement",
        required=True,
        help="Describe the requested pixel-art result",
    )
    pixel_universal_run.add_argument(
        "--view",
        default="standard",
        choices=["standard", "top-down"],
        help="Use a normal composition or a top-down game view",
    )
    pixel_universal_run.add_argument(
        "--reference-image",
        action="append",
        default=[],
        help="Optional style or content reference; can be repeated",
    )
    pixel_universal_run.add_argument(
        "--remove-bg-method",
        default="none",
        choices=["none", "standard"],
        help="Keep the composed background or remove a simple background",
    )

    pixel_poll = subparsers.add_parser("pixel-gen-poll", help="Poll one pixel-gen job")
    add_shared_path_args(pixel_poll)
    pixel_poll.add_argument("--api-job-id", required=True)

    pixel_history = subparsers.add_parser("pixel-gen-history", help="Query pixel-gen history")
    add_shared_path_args(pixel_history)
    pixel_history.add_argument("--limit", type=int, default=20)
    pixel_history.add_argument("--offset", type=int, default=0)
    pixel_history.add_argument("--status", default="")

    pixel_download = subparsers.add_parser("pixel-gen-download", help="Download pixel-gen output")
    add_shared_path_args(pixel_download)
    pixel_download.add_argument("--api-job-id", required=True)
    pixel_download.add_argument("--output-index", type=int, default=None)

    pixel_cancel = subparsers.add_parser("pixel-gen-cancel", help="Cancel one pixel-gen job")
    add_shared_path_args(pixel_cancel)
    pixel_cancel.add_argument("--api-job-id", required=True)

    subparsers.add_parser("hd-gen-template-info", help="List HD asset presets")

    hd_submit = subparsers.add_parser("hd-gen-submit", help="Submit an HD-gen job")
    add_shared_path_args(hd_submit)
    hd_submit.add_argument("--template-name", required=True)
    hd_submit.add_argument("--requirement", required=True)
    hd_submit.set_defaults(template_config="{}")
    hd_submit.add_argument("--job-name", default="")
    hd_submit.add_argument("--resolution", default="", help="Optional resolution; empty uses template default")
    hd_submit.add_argument("--aspect-ratio", default="1:1")
    hd_submit.add_argument(
        "--quality",
        dest="quality_mode",
        default="standard",
        choices=["standard", "detailed", "ultimate"],
        help="Output quality: Standard, Detailed, or Ultimate",
    )
    hd_submit.add_argument(
        "--remove-bg-method",
        default="standard",
        choices=["none", "standard", "advanced"],
        help="Background removal: none, standard, or advanced",
    )
    hd_submit.add_argument("--reference-file", default="", help="Optional single user reference image")
    hd_submit.add_argument("--reference-files", action="append", default=[], help="Optional user reference image; can be repeated")
    hd_submit.set_defaults(project_id=None, thread_id=None)

    hd_run = subparsers.add_parser("hd-gen-run", help="Create an HD game asset from a preset")
    for action in hd_submit._actions[1:]:
        if action.dest not in {"help", "job_name"}:
            hd_run._add_action(action)
    hd_run.set_defaults(job_name="")
    add_shared_runtime_args(hd_run)

    hd_poll = subparsers.add_parser("hd-gen-poll", help="Poll one HD-gen job")
    add_shared_path_args(hd_poll)
    hd_poll.add_argument("--api-job-id", required=True)

    hd_history = subparsers.add_parser("hd-gen-history", help="Query HD-gen history")
    add_shared_path_args(hd_history)
    hd_history.add_argument("--limit", type=int, default=20)
    hd_history.add_argument("--offset", type=int, default=0)
    hd_history.add_argument("--status", default="")

    hd_download = subparsers.add_parser("hd-gen-download", help="Download HD-gen output")
    add_shared_path_args(hd_download)
    hd_download.add_argument("--api-job-id", required=True)
    hd_download.add_argument("--output-index", type=int, default=None)

    hd_cancel = subparsers.add_parser("hd-gen-cancel", help="Cancel one HD-gen job")
    add_shared_path_args(hd_cancel)
    hd_cancel.add_argument("--api-job-id", required=True)

    character_multi_view_submit = subparsers.add_parser(
        "character-multi-view-submit",
        aliases=["character-8-direction-submit", "character-eight-direction-submit"],
        help="Submit character_multi_view_generator",
    )
    add_shared_path_args(character_multi_view_submit)
    character_multi_view_submit.add_argument(
        "--reference-image",
        "--image-file",
        dest="reference_image",
        required=True,
        help="Existing character reference image",
    )
    character_multi_view_submit.add_argument("--mode", default="pixel", choices=["pixel", "hd"])
    character_multi_view_submit.add_argument("--canvas-resolution", default="1K", choices=["1K", "2K"])
    character_multi_view_submit.add_argument("--direction-mode", default="mirror", choices=["mirror", "ninegrid"])
    character_multi_view_submit.add_argument("--aspect-ratio", default="", choices=["", "1:1", "3:4", "9:16"])
    character_multi_view_submit.add_argument(
        "--remove-bg-method",
        default="standard",
        choices=["none", "standard", "advanced"],
    )
    character_multi_view_submit.add_argument("--extra-constraint", default="")
    character_multi_view_submit.add_argument("--output-size", type=int, default=None, help="Optional final square sprite size")
    character_multi_view_submit.set_defaults(project_id=None, thread_id=None)

    character_multi_view_run = subparsers.add_parser(
        "character-multi-view-run",
        aliases=["character-8-direction-run", "character-eight-direction-run"],
        help="Create an eight-direction character sheet",
    )
    for action in character_multi_view_submit._actions[1:]:
        if action.dest not in {"help"}:
            character_multi_view_run._add_action(action)
    add_shared_runtime_args(character_multi_view_run)

    character_multi_view_poll = subparsers.add_parser(
        "character-multi-view-poll",
        aliases=["character-8-direction-poll", "character-eight-direction-poll"],
        help="Poll one character_multi_view_generator workflow job",
    )
    add_shared_path_args(character_multi_view_poll)
    character_multi_view_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    remove_bg_submit = subparsers.add_parser("remove-background-submit", help="Submit a remove-background job")
    add_shared_path_args(remove_bg_submit)
    remove_bg_submit.add_argument("--image-file", required=True)
    remove_bg_submit.add_argument("--mode", default="hd", choices=["pixel", "hd"], help="Source artwork type")
    remove_bg_submit.add_argument("--quality", default="standard", choices=["standard", "advanced"])
    remove_bg_submit.add_argument("--prompt", default="", help="Optional subject description for complex backgrounds")

    remove_bg_run = subparsers.add_parser("remove-background-run", help="Create a transparent-background asset")
    for action in remove_bg_submit._actions[1:]:
        if action.dest not in {"help"}:
            remove_bg_run._add_action(action)
    add_shared_runtime_args(remove_bg_run)

    pixelate_submit = subparsers.add_parser("pixelate-submit", help="Submit a pixelate job")
    add_shared_path_args(pixelate_submit)
    pixelate_submit.add_argument("--image-file", required=True)
    pixelate_submit.add_argument("--pixel-size", default="")

    pixelate_run = subparsers.add_parser("pixelate-run", help="Convert artwork into crisp pixel art")
    for action in pixelate_submit._actions[1:]:
        if action.dest not in {"help", "pixel_size"}:
            pixelate_run._add_action(action)
    pixelate_run.set_defaults(pixel_size="")
    add_shared_runtime_args(pixelate_run)

    self_loop_submit = subparsers.add_parser("self-loop-submit", help="Submit a pixel_gen_self_loop job")
    add_shared_path_args(self_loop_submit)
    self_loop_submit.add_argument("--image-file", required=True)
    self_loop_submit.add_argument("--job-name", default="")
    self_loop_submit.add_argument("--resolution", default="1K")
    self_loop_submit.add_argument("--mode", choices=["basic", "full", "texture"], default="basic")
    self_loop_submit.add_argument("--direction", choices=["horizontal", "vertical"], default="horizontal")

    self_loop_run = subparsers.add_parser("self-loop-run", help="Create a seamless loop from an image")
    for action in self_loop_submit._actions[1:]:
        if action.dest not in {"help", "requirement", "job_name"}:
            self_loop_run._add_action(action)
    self_loop_run.set_defaults(job_name="")
    add_shared_runtime_args(self_loop_run)

    def add_sound_args(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--prompt", required=True, help="Sound effect requirement")
        command_parser.add_argument("--duration", type=float, default=2, help="0.5 or integer seconds from 1 to 10")
        command_parser.add_argument("--loop", action="store_true", help="Request a loopable sound")
        sound_kind = command_parser.add_mutually_exclusive_group()
        sound_kind.add_argument("--sound-pack", action="store_true", help="Generate a pack of different sounds")
        sound_kind.add_argument("--variants", action="store_true", help="Generate variants of the same sound")
        command_parser.add_argument("--count", type=int, default=4, help="Number of pack items or variants")
        command_parser.add_argument("--language", default="en", help="Name language; prompt generation stays English")

    sound_submit = subparsers.add_parser("sound-submit", aliases=["sfx-submit", "sound-effect-submit"], help="Submit a sound-effect job")
    add_shared_path_args(sound_submit)
    add_sound_args(sound_submit)

    sound_run = subparsers.add_parser("sound-run", aliases=["sfx-run", "sound-effect-run"], help="Submit and wait for sound effects")
    add_shared_path_args(sound_run)
    add_sound_args(sound_run)
    add_shared_runtime_args(sound_run)

    sound_poll = subparsers.add_parser("sound-poll", aliases=["sfx-poll", "sound-effect-poll"], help="Poll one sound-effect workflow job")
    add_shared_path_args(sound_poll)
    sound_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    texture_submit = subparsers.add_parser("texture-gen-submit", help="Submit a texture_gen job")
    add_shared_path_args(texture_submit)
    texture_submit.add_argument("--prompt", required=True, help="Describe the required 64x64 seamless texture")
    texture_submit.add_argument("--self-loop", action="store_true", default=True)
    texture_submit.add_argument("--no-self-loop", action="store_false", dest="self_loop")
    texture_submit.set_defaults(project_id=None, thread_id=None)

    texture_run = subparsers.add_parser("texture-gen-run", help="Create a seamless texture")
    for action in texture_submit._actions[1:]:
        if action.dest not in {"help"}:
            texture_run._add_action(action)
    texture_run.set_defaults(project_id=None, thread_id=None)
    add_shared_runtime_args(texture_run)

    texture_poll = subparsers.add_parser("texture-gen-poll", help="Poll one texture_gen workflow job")
    add_shared_path_args(texture_poll)
    texture_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    tileset_submit = subparsers.add_parser("tileset-gen-submit", help="Submit a tileset_gen job")
    add_shared_path_args(tileset_submit)
    tileset_submit.add_argument("--prompt", default="", help="Optional transition or style instruction")
    tileset_submit.add_argument(
        "--terrain-mode",
        required=True,
        choices=["foreground", "background", "dual"],
        help="Generate only the foreground, only the background, or both terrains",
    )
    tileset_submit.add_argument("--foreground-texture", default="", help="Exact 64x64 foreground texture")
    tileset_submit.add_argument("--background-texture", default="", help="Exact 64x64 background texture")
    tileset_submit.add_argument(
        "--remove-bg-method",
        default="standard",
        choices=["none", "standard", "advanced"],
        help="Used only when exactly one texture is supplied; default: standard",
    )
    tileset_submit.set_defaults(project_id=None, thread_id=None)

    tileset_run = subparsers.add_parser("tileset-gen-run", help="Create a terrain tileset")
    for action in tileset_submit._actions[1:]:
        if action.dest not in {"help"}:
            tileset_run._add_action(action)
    tileset_run.set_defaults(project_id=None, thread_id=None)
    add_shared_runtime_args(tileset_run)

    tileset_poll = subparsers.add_parser("tileset-gen-poll", help="Poll one tileset_gen workflow job")
    add_shared_path_args(tileset_poll)
    tileset_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    ui_submit = subparsers.add_parser("ui-gen-submit", aliases=["general-ui-gen-submit"], help="Submit a general_ui_gen job")
    add_shared_path_args(ui_submit)
    ui_submit.add_argument("--prompt", required=True, help="Game UI sheet, HUD, menu, button, or icon requirement")
    ui_submit.add_argument(
        "--reference-image",
        "--reference-file",
        dest="reference_image",
        action="append",
        default=[],
        help="Required in extract mode; optional style reference in generate mode; repeat up to 8 times",
    )
    ui_submit.add_argument("--resolution", default="2K", choices=["1K", "2K"])
    ui_submit.add_argument("--aspect-ratio", default="1:1", choices=["4:3", "3:4", "16:9", "9:16", "1:1"])
    ui_submit.add_argument(
        "--quality",
        default="detailed",
        choices=["standard", "detailed", "ultimate"],
        help="Output quality: Standard, Detailed, or Ultimate",
    )
    ui_submit.add_argument(
        "--remove-bg-method",
        default="standard",
        choices=["none", "standard", "advanced"],
        help="Background removal: none, standard, or advanced",
    )
    ui_submit.add_argument("--mode", dest="generation_mode", default="generate", choices=["generate", "extract"])
    ui_submit.set_defaults(
        template="hd_retro_rpg",
        generation_provider="image2",
        split_components=True,
        project_id=None,
        thread_id=None,
    )

    ui_run = subparsers.add_parser("ui-gen-run", aliases=["general-ui-gen-run"], help="Create or extract game UI assets")
    for action in ui_submit._actions[1:]:
        if action.dest not in {"help"}:
            ui_run._add_action(action)
    add_shared_runtime_args(ui_run)

    ui_poll = subparsers.add_parser("ui-gen-poll", aliases=["general-ui-gen-poll"], help="Poll one general_ui_gen workflow job")
    add_shared_path_args(ui_poll)
    ui_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    isometric_submit = subparsers.add_parser(
        "isometric-gen-submit",
        aliases=["pixel-isometric-gen-submit"],
        help="Submit pixel_isometric_gen",
    )
    add_shared_path_args(isometric_submit)
    add_map_workflow_args(
        isometric_submit,
        modes=("standard", "edit", "tetraploid", "road", "wall"),
        include_remove_bg=True,
    )

    isometric_run = subparsers.add_parser(
        "isometric-gen-run",
        aliases=["pixel-isometric-gen-run"],
        help="Create pixel isometric map tiles",
    )
    for action in isometric_submit._actions[1:]:
        if action.dest not in {"help"}:
            isometric_run._add_action(action)
    add_shared_runtime_args(isometric_run)

    isometric_poll = subparsers.add_parser(
        "isometric-gen-poll",
        aliases=["pixel-isometric-gen-poll"],
        help="Poll one pixel_isometric_gen workflow job",
    )
    add_shared_path_args(isometric_poll)
    isometric_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    hex_isometric_submit = subparsers.add_parser(
        "hex-isometric-gen-submit",
        aliases=["pixel-hex-isometric-gen-submit"],
        help="Submit pixel_hex_isometric_gen",
    )
    add_shared_path_args(hex_isometric_submit)
    add_map_workflow_args(
        hex_isometric_submit,
        modes=("standard", "edit", "tetraploid", "heptaploid"),
        include_remove_bg=True,
    )

    hex_isometric_run = subparsers.add_parser(
        "hex-isometric-gen-run",
        aliases=["pixel-hex-isometric-gen-run"],
        help="Create pixel hex-isometric map tiles",
    )
    for action in hex_isometric_submit._actions[1:]:
        if action.dest not in {"help"}:
            hex_isometric_run._add_action(action)
    add_shared_runtime_args(hex_isometric_run)

    hex_isometric_poll = subparsers.add_parser(
        "hex-isometric-gen-poll",
        aliases=["pixel-hex-isometric-gen-poll"],
        help="Poll one pixel_hex_isometric_gen workflow job",
    )
    add_shared_path_args(hex_isometric_poll)
    hex_isometric_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    hd_isometric_submit = subparsers.add_parser("hd-isometric-gen-submit", help="Submit hd_isometric_gen")
    add_shared_path_args(hd_isometric_submit)
    add_map_workflow_args(
        hd_isometric_submit,
        modes=("standard", "tetraploid"),
        include_template=True,
    )

    hd_isometric_run = subparsers.add_parser("hd-isometric-gen-run", help="Create HD isometric map tiles")
    for action in hd_isometric_submit._actions[1:]:
        if action.dest not in {"help"}:
            hd_isometric_run._add_action(action)
    add_shared_runtime_args(hd_isometric_run)

    hd_isometric_poll = subparsers.add_parser("hd-isometric-gen-poll", help="Poll one hd_isometric_gen workflow job")
    add_shared_path_args(hd_isometric_poll)
    hd_isometric_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    hd_hex_isometric_submit = subparsers.add_parser("hd-hex-isometric-gen-submit", help="Submit hd_hex_isometric_gen")
    add_shared_path_args(hd_hex_isometric_submit)
    add_map_workflow_args(
        hd_hex_isometric_submit,
        modes=("standard", "tetraploid"),
        include_template=True,
    )

    hd_hex_isometric_run = subparsers.add_parser("hd-hex-isometric-gen-run", help="Create HD hex-isometric map tiles")
    for action in hd_hex_isometric_submit._actions[1:]:
        if action.dest not in {"help"}:
            hd_hex_isometric_run._add_action(action)
    add_shared_runtime_args(hd_hex_isometric_run)

    hd_hex_isometric_poll = subparsers.add_parser("hd-hex-isometric-gen-poll", help="Poll one hd_hex_isometric_gen workflow job")
    add_shared_path_args(hd_hex_isometric_poll)
    hd_hex_isometric_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    music_submit = subparsers.add_parser("music-submit", help="Submit a music_generator job")
    add_shared_path_args(music_submit)
    music_submit.add_argument("--prompt", default="", help="Music requirement text; optional when reference images are provided")
    music_submit.add_argument("--generate-audio", dest="audio_generate", action="store_true", help="Render a playable track")
    music_submit.add_argument("--preview", dest="demo", action="store_true", help="Render a shorter preview")
    music_submit.add_argument("--reference-image", action="append", default=[], help="Optional reference image; can be repeated")

    music_run = subparsers.add_parser("music-run", help="Draft or render game music")
    for action in music_submit._actions[1:]:
        if action.dest not in {"help"}:
            music_run._add_action(action)
    add_shared_runtime_args(music_run)

    music_poll = subparsers.add_parser("music-poll", help="Poll one music/workflow job")
    add_shared_path_args(music_poll)
    music_poll.add_argument("--api-job-id", "--job-id", dest="api_job_id", required=True)

    subparsers.add_parser("credits-balance", help="Get current credits balance")

    animate_submit_parser = subparsers.add_parser("animate-submit", help="Submit an animate job")
    add_shared_path_args(animate_submit_parser)
    animate_submit_parser.add_argument("--image-file", required=True)
    animate_submit_parser.add_argument("--prompt", default="")
    animate_submit_parser.add_argument("--is-pixel", action="store_true")
    animate_submit_parser.add_argument("--output-frames", type=int, default=8)
    animate_submit_parser.add_argument("--output-format", default="webp", choices=["webp", "gif", "spritesheet"])
    animate_submit_parser.add_argument("--animation-type", default="other")
    animate_submit_parser.add_argument(
        "--remove-bg-method",
        default="advanced",
        choices=["none", "standard", "advanced"],
    )

    animate_run_parser = subparsers.add_parser("animate-run", help="Create a short sprite animation")
    for action in animate_submit_parser._actions[1:]:
        if action.dest not in {"help"}:
            animate_run_parser._add_action(action)
    add_shared_runtime_args(animate_run_parser)

    keyframes_run_parser = subparsers.add_parser(
        "keyframes-run",
        help="Create frame animation controlled by two or more keyframes",
    )
    add_shared_path_args(keyframes_run_parser)
    keyframes_run_parser.add_argument(
        "--keyframe",
        action="append",
        required=True,
        help="Keyframe in INDEX=PATH form; repeat at least twice and include index 0",
    )
    keyframes_run_parser.add_argument("--prompt", required=True)
    keyframes_run_parser.add_argument("--total-frames", type=int, default=8)
    keyframes_run_parser.add_argument("--output-format", default="webp", choices=["webp", "gif", "spritesheet"])
    keyframes_run_parser.add_argument(
        "--animation-type",
        default="other",
        choices=["idle", "walk", "run", "jump", "attack", "hit", "defeated", "other"],
    )
    keyframes_run_parser.add_argument(
        "--remove-bg-method",
        default="advanced",
        choices=["none", "standard", "advanced"],
    )
    add_shared_runtime_args(keyframes_run_parser)

    animate_poll_parser = subparsers.add_parser("animate-poll", help="Poll one animate job")
    add_shared_path_args(animate_poll_parser)
    animate_poll_parser.add_argument("--api-job-id", required=True)

    public_commands = {
        "map-reference-search",
        "map-reference-download",
        "texture-reference-search",
        "texture-reference-download",
        "nano-banana-run",
        "image-2-run",
        "image-edit-run",
        "animation-edit-run",
        "one-click-upgrade-prompts",
        "one-click-upgrade-run",
        "video-prompt-list",
        "video-run",
        "isometric-texture-run",
        "isometric-tileset-run",
        "side-scrolling-map-run",
        "hd-side-scrolling-map-run",
        "pixel-gen-template-info",
        "pixel-gen-run",
        "large-pixel-template-info",
        "large-pixel-gen-run",
        "pixel-universal-gen-run",
        "hd-gen-template-info",
        "hd-gen-run",
        "character-multi-view-run",
        "remove-background-run",
        "pixelate-run",
        "self-loop-run",
        "sound-run",
        "texture-gen-run",
        "tileset-gen-run",
        "ui-gen-run",
        "isometric-gen-run",
        "hex-isometric-gen-run",
        "hd-isometric-gen-run",
        "hd-hex-isometric-gen-run",
        "music-run",
        "credits-balance",
        "animate-run",
        "keyframes-run",
    }
    subparsers._choices_actions[:] = [
        action for action in subparsers._choices_actions if action.dest in public_commands
    ]
    for action in subparsers._choices_actions:
        action.metavar = action.dest

    return parser.parse_args()


def _parse_json_arg(raw: str, *, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    return payload


def _read_dotenv_value(key: str) -> str:
    candidate_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    seen: set[Path] = set()
    for path in candidate_paths:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        for line in resolved.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() != key:
                continue
            return value.strip().strip("'\"")
    return ""


def _resolve_auth_token() -> str:
    env_api_key = os.getenv(DEFAULT_API_KEY_ENV, "").strip()
    if env_api_key:
        return env_api_key

    dotenv_api_key = _read_dotenv_value(DEFAULT_API_KEY_ENV).strip()
    if dotenv_api_key:
        return dotenv_api_key

    env_dev_key = os.getenv(DEFAULT_DEV_KEY_ENV, "").strip()
    if env_dev_key:
        return f"{_DEV_AUTH_PREFIX}{env_dev_key}"

    dotenv_dev_key = _read_dotenv_value(DEFAULT_DEV_KEY_ENV).strip()
    if dotenv_dev_key:
        return f"{_DEV_AUTH_PREFIX}{dotenv_dev_key}"

    raise ValueError(
        "Meowa authentication is not configured. Configure credentials outside the command line and retry."
    )

def main() -> int:
    _configure_stdio()
    args = parse_args()
    verify = not args.insecure

    started_at = datetime.now().isoformat(timespec="seconds")
    run_dir = _create_run_dir(args.work_dir, args.command)
    effective_output_dir = _resolve_output_dir(args.output_dir, run_dir)
    try:
        no_auth_commands = {
            "map-reference-search",
            "map-preset-search",
            "map-reference-download",
            "map-preset-download",
            "texture-reference-search",
            "texture-reference-download",
        }
        needs_api_key = args.command not in no_auth_commands
        args.api_key = _resolve_auth_token() if needs_api_key else ""

        if args.command == "video-prompt-list":
            payload = submit_curated_workflow(
                api_base=args.api_base,
                api_key=args.api_key,
                endpoint="/api/workflows/seedance_generator/run",
                data={
                    "get_prompt": "true",
                    "model_name": _video_model_name(args.motion_mode),
                },
                timeout=args.timeout,
                verify=verify,
            )
            print(_format_public_json(payload))
            return 0

        if args.command == "one-click-upgrade-prompts":
            payload = design_one_click_upgrade_prompts(
                api_base=args.api_base,
                api_key=args.api_key,
                reference_image=args.reference_image,
                prompt=args.prompt,
                count=args.count,
                language=args.language,
                timeout=args.timeout,
                verify=verify,
            )
            print(_format_public_json(payload))
            return 0

        if args.command in {"map-reference-search", "map-preset-search"}:
            workflow_id, template_id, group = _resolve_map_reference_filters(
                map_type=args.map_type,
                theme=args.theme,
                layout=args.layout,
                group=args.group,
            )
            if args.categories:
                if any((args.query, args.theme, args.layout, args.tile_size, args.asset_kind, args.group)):
                    raise ValueError("--categories accepts only the optional --type filter")
                catalog = fetch_map_preset_catalog(
                    api_base=args.api_base,
                    timeout=args.timeout,
                    verify=verify,
                )
                payload = public_map_reference_categories(catalog, map_type=args.map_type)
                _write_meta(
                    run_dir=run_dir,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    args=args,
                    request_payload={"categories": True, "type": args.map_type},
                    response_payload=payload,
                    downloads=[],
                    effective_output_dir=str(effective_output_dir),
                )
                print(_format_public_json(payload))
                return 0
            payload = search_map_presets(
                api_base=args.api_base,
                query=args.query,
                workflow_id=workflow_id,
                template_id=template_id,
                tile_size=args.tile_size,
                asset_kind=args.asset_kind,
                group=group,
                limit=args.limit,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "query": args.query,
                    "type": args.map_type,
                    "theme": args.theme,
                    "layout": args.layout,
                    "tile_size": args.tile_size,
                    "asset_kind": args.asset_kind,
                    "group": group,
                    "limit": args.limit,
                },
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_public_json(_public_map_search_payload(payload)))
            return 0

        if args.command in {"map-reference-download", "map-preset-download"}:
            workflow_id, template_id, group = _resolve_map_reference_filters(
                map_type=args.map_type,
                theme=args.theme,
                layout=args.layout,
                group=args.group,
            )
            public_search_payload, downloads = download_map_presets(
                api_base=args.api_base,
                query=args.query,
                preset_ids=list(args.preset_id or []),
                workflow_id=workflow_id,
                template_id=template_id,
                tile_size=args.tile_size,
                asset_kind=args.asset_kind,
                group=group,
                limit=args.limit,
                output_dir=str(effective_output_dir),
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "preset_ids": list(args.preset_id or []),
                    "query": args.query,
                    "type": args.map_type,
                    "theme": args.theme,
                    "layout": args.layout,
                    "tile_size": args.tile_size,
                    "asset_kind": args.asset_kind,
                    "group": group,
                    "limit": args.limit,
                },
                response_payload=public_search_payload,
                downloads=downloads,
                effective_output_dir=str(effective_output_dir),
            )
            print(f"[INFO] saved_dir={effective_output_dir}")
            print(_format_public_json(public_search_payload))
            return 0

        if args.command == "texture-reference-search":
            if args.categories:
                if args.query or args.category:
                    raise ValueError("--categories cannot be combined with --query or --category")
                catalog = fetch_texture_reference_catalog(
                    api_base=args.api_base,
                    timeout=args.timeout,
                    verify=verify,
                )
                payload = public_texture_reference_categories(catalog)
            else:
                payload = search_texture_references(
                    api_base=args.api_base,
                    query=args.query,
                    category=args.category,
                    limit=args.limit,
                    timeout=args.timeout,
                    verify=verify,
                )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "query": args.query,
                    "category": args.category,
                    "categories": args.categories,
                    "limit": args.limit,
                },
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_public_json(payload))
            return 0

        if args.command == "texture-reference-download":
            public_search_payload, downloads = download_texture_references(
                api_base=args.api_base,
                reference_ids=list(args.reference_id or []),
                query=args.query,
                category=args.category,
                limit=args.limit,
                output_dir=str(effective_output_dir),
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "reference_ids": list(args.reference_id or []),
                    "query": args.query,
                    "category": args.category,
                    "limit": args.limit,
                },
                response_payload=public_search_payload,
                downloads=downloads,
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_public_json(public_search_payload))
            return 0

        if args.command in {"nano-banana-run", "image-2-run"}:
            capability = "nano-banana" if args.command == "nano-banana-run" else "image-2"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, args.prompt)}")
            submit_payload, final_payload = run_general_image(
                api_base=args.api_base,
                api_key=args.api_key,
                capability=capability,
                prompt=args.prompt,
                reference_images=list(args.reference_image or []),
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                quality=getattr(args, "quality", "standard"),
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, _downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.prompt,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="gemini_image",
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        curated_commands = {
            "image-edit-run",
            "animation-edit-run",
            "one-click-upgrade-run",
            "video-run",
            "isometric-texture-run",
            "isometric-tileset-run",
            "side-scrolling-map-run",
            "hd-side-scrolling-map-run",
        }
        if args.command in curated_commands:
            endpoint = ""
            workflow_id = ""
            slug_seed = "asset"
            data: dict[str, str] = {}
            files: list[tuple[str, tuple[str, bytes, str]]] = []

            if args.command == "image-edit-run":
                references = list(args.reference_image or [])
                if not 1 <= len(references) <= 8:
                    raise ValueError("image editing requires 1 to 8 reference images")
                if args.strict and args.mode != "pixel":
                    raise ValueError("--strict is available only in pixel mode")
                endpoint = "/api/workflows/image_edit/run"
                workflow_id = "image_edit"
                slug_seed = args.prompt
                data = {
                    "prompt": args.prompt,
                    "mode": args.mode,
                    "strict": "true" if args.strict else "false",
                    "remove_bg_method": args.remove_bg_method if args.mode == "pixel" else "none",
                    "resolution": args.resolution,
                    "aspect_ratio": args.aspect_ratio,
                }
                files.extend(("reference_images", _upload_part(path, label="reference image")) for path in references)

            elif args.command == "animation-edit-run":
                animation_path = Path(args.animation_file).expanduser()
                if animation_path.suffix.lower() not in {".gif", ".webp"}:
                    raise ValueError("animation editing accepts animated GIF or WebP files")
                references = list(args.reference_image or [])
                if len(references) > 8:
                    raise ValueError("animation editing accepts at most 8 reference images")
                endpoint = "/api/workflows/frames_edit/run"
                workflow_id = "frames_edit"
                slug_seed = args.prompt
                data = {
                    "prompt": args.prompt,
                    "mode": args.mode,
                    "remove_bg_method": args.remove_bg_method,
                }
                files.append(("source_animation", _upload_part(args.animation_file, label="animation file")))
                files.extend(("reference_images", _upload_part(path, label="reference image")) for path in references)

            elif args.command == "one-click-upgrade-run":
                prompts = [str(prompt or "").strip() for prompt in args.variant_prompt]
                if not 1 <= len(prompts) <= 8:
                    raise ValueError("one-click upgrade requires 1 to 8 --variant-prompt values")
                if any(not prompt for prompt in prompts):
                    raise ValueError("--variant-prompt values must not be empty")
                if args.mode == "hd" and args.remove_bg_method == "advanced":
                    raise ValueError("HD one-click upgrade supports only none or standard background removal")
                endpoint = ONE_CLICK_UPGRADE_ENDPOINT
                workflow_id = "one_click_upgrade"
                slug_seed = prompts[0]
                data = {
                    "prompt_list": json.dumps(prompts, ensure_ascii=False),
                    "count": str(len(prompts)),
                    "mode": args.mode,
                    "remove_bg_method": args.remove_bg_method,
                }
                if args.resolution:
                    data["resolution"] = args.resolution
                files.append(("reference_image", _upload_part(args.reference_image, label="reference image")))

            elif args.command == "video-run":
                if not args.prompt.strip() and not (args.action.strip() and args.direction.strip()):
                    raise ValueError("video generation requires --prompt or both --action and --direction")
                endpoint = "/api/workflows/seedance_generator/run"
                workflow_id = "seedance_generator"
                slug_seed = args.prompt or f"{args.action}-{args.direction}"
                data = {
                    "prompt": args.prompt,
                    "action": args.action,
                    "direction": args.direction,
                    "pixel": "true" if args.pixel else "false",
                    "resolution": args.resolution,
                    "reference_mode": "first_last" if args.last_frame else "reference_image",
                    "frame_count": str(args.frame_count),
                    "animation_type": args.animation_type,
                    "model_name": _video_model_name(args.motion_mode),
                }
                files.append(("file", _upload_part(args.first_frame, label="first frame")))
                if args.last_frame:
                    files.append(("last_file", _upload_part(args.last_frame, label="last frame")))

            elif args.command == "isometric-texture-run":
                references = list(args.reference_image or [])
                if not args.prompt.strip() and not args.preset.strip() and not args.texture_name and not references:
                    raise ValueError("isometric texture generation requires a prompt, preset, texture name, or reference image")
                endpoint = "/api/workflows/isometric_texture_gen/run"
                workflow_id = "isometric_texture_gen"
                slug_seed = args.prompt or args.preset or "isometric-texture"
                data = {
                    "prompt": args.prompt,
                    "template": args.preset,
                    "texture_names": ",".join(list(args.texture_name or [])),
                    "self_loop": "true" if args.self_loop else "false",
                }
                files.extend(("reference_files", _upload_part(path, label="reference image")) for path in references)

            elif args.command == "isometric-tileset-run":
                endpoint = "/api/workflows/isometric_tileset_gen/run"
                workflow_id = "isometric_tileset_gen"
                slug_seed = args.prompt or "isometric-tileset"
                data = {
                    "prompt": args.prompt,
                    "terrain_mode": args.terrain_mode,
                    "single_terrain_region": args.single_terrain_region,
                    "single_terrain_show_base_color": "true" if args.show_base_color else "false",
                    "remove_bg_method": args.remove_bg_method if args.terrain_mode == "single" else "none",
                    "foreground_color": args.foreground_color,
                    "background_color": args.background_color,
                    "terrain_color": args.terrain_color,
                }
                if args.foreground_texture:
                    files.append(("foreground_texture", _upload_part(args.foreground_texture, label="foreground texture")))
                if args.background_texture:
                    files.append(("background_texture", _upload_part(args.background_texture, label="background texture")))

            elif args.command == "side-scrolling-map-run":
                endpoint = "/api/workflows/side_scrolling_map_gen/run"
                workflow_id = "side_scrolling_map_gen"
                slug_seed = args.midground
                data = {
                    "midground_input": args.midground,
                    "background_input": args.background,
                    "foreground_input": args.foreground,
                    "mode": "full",
                    "remove_bg_method": args.remove_bg_method,
                    "resolution": "1K",
                    "aspect_ratio": "16:9",
                    "loop_midground": "true" if args.loop_midground else "false",
                    "loop_background": "true" if args.loop_background else "false",
                    "loop_foreground": "true" if args.loop_foreground else "false",
                }

            elif args.command == "hd-side-scrolling-map-run":
                endpoint = "/api/workflows/hd_side_scrolling_map_gen/run"
                workflow_id = "hd_side_scrolling_map_gen"
                slug_seed = args.midground
                data = {
                    "midground_input": args.midground,
                    "background_input": args.background,
                    "foreground_input": args.foreground,
                    "mode": "full",
                    "resolution": "1K",
                    "aspect_ratio": "16:9",
                    "art_style": args.art_style,
                    "custom_art_style": args.custom_art_style,
                    "loop_midground": "true" if args.loop_midground else "false",
                    "loop_background": "true" if args.loop_background else "false",
                    "loop_foreground": "true" if args.loop_foreground else "false",
                }

            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            submit_payload, final_payload = run_curated_workflow(
                api_base=args.api_base,
                api_key=args.api_key,
                endpoint=endpoint,
                label=args.command.removesuffix("-run"),
                data=data,
                files=files,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id=workflow_id,
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command in {"pixel-gen-template-info", "large-pixel-template-info"}:
            payload = pixel_gen_template_info(
                api_base=args.api_base,
                api_key=args.api_key,
                workflow_id=(
                    PIXEL_GENERAL_WORKFLOW_ID
                    if args.command == "large-pixel-template-info"
                    else ""
                ),
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_public_json(payload))
            return 0

        if args.command in {"large-pixel-gen-run", "pixel-universal-gen-run"}:
            references = list(args.reference_image or [])
            template_config: dict[str, Any] = {}
            if args.remove_bg_method:
                template_config["remove_bg_method"] = args.remove_bg_method

            if args.command == "large-pixel-gen-run":
                template_name = args.template_name
                validate_pixel_general_template(
                    api_base=args.api_base,
                    api_key=args.api_key,
                    template_name=template_name,
                    timeout=args.timeout,
                    verify=verify,
                )
            else:
                template_name = PIXEL_UNIVERSAL_TEMPLATE_NAME
                if args.view == "top-down":
                    template_config["direction"] = "top-down"

            predicted_output_dir = _predict_saved_dir(effective_output_dir, args.requirement)
            print(f"[INFO] planned_output_dir={predicted_output_dir}")
            submit_payload, final_payload = run_pixel_gen(
                api_base=args.api_base,
                api_key=args.api_key,
                template_name=template_name,
                requirement=args.requirement,
                template_config=template_config,
                reference_file=references[0] if references else "",
                reference_files=references[1:],
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, _downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.requirement,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id=PIXEL_GENERAL_WORKFLOW_ID,
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "pixel-gen-submit":
            payload = submit_pixel_gen(
                api_base=args.api_base,
                api_key=args.api_key,
                template_name=args.template_name,
                requirement=args.requirement,
                template_config=_parse_json_arg(args.template_config, name="template_config"),
                job_name=args.job_name,
                aspect_ratio=args.aspect_ratio,
                reference_file=args.reference_file,
                reference_files=list(args.reference_files or []),
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "template_name": args.template_name,
                    "requirement": args.requirement,
                    "template_config": _parse_json_arg(args.template_config, name="template_config"),
                    "job_name": args.job_name,
                    "aspect_ratio": args.aspect_ratio,
                    "reference_file": args.reference_file,
                    "reference_files": list(args.reference_files or []),
                },
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "pixel-gen-run":
            template_config = _parse_json_arg(args.template_config, name="template_config")
            request_payload = {
                "template_name": args.template_name,
                "requirement": args.requirement,
                "template_config": template_config,
                "job_name": args.job_name,
                "aspect_ratio": args.aspect_ratio,
                "reference_file": args.reference_file,
                "reference_files": list(args.reference_files or []),
            }
            predicted_output_dir = _predict_saved_dir(effective_output_dir, args.job_name or args.requirement)
            print(f"[INFO] planned_output_dir={predicted_output_dir}")
            submit_payload = submit_pixel_gen(
                api_base=args.api_base,
                api_key=args.api_key,
                template_name=args.template_name,
                requirement=args.requirement,
                template_config=template_config,
                job_name=args.job_name,
                aspect_ratio=args.aspect_ratio,
                reference_file=args.reference_file,
                reference_files=list(args.reference_files or []),
                timeout=args.timeout,
                verify=verify,
            )
            api_job_id = str(submit_payload.get("api_job_id") or "").strip()
            if not api_job_id:
                raise RuntimeError("pixel-gen submit response missing api_job_id")
            print(f"[INFO] submitted api_job_id={api_job_id}")
            print("[INFO] waiting_for_completion")
            final_payload = wait_pixel_gen_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=api_job_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.job_name or args.requirement,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="pixel_gen",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "pixel-gen-poll":
            payload = poll_pixel_gen_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "pixel-gen-history":
            payload = pixel_gen_history(
                api_base=args.api_base,
                api_key=args.api_key,
                limit=args.limit,
                offset=args.offset,
                status=args.status,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"limit": args.limit, "offset": args.offset, "status": args.status},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "pixel-gen-download":
            path = pixel_gen_download(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                output_dir=args.output_dir or str(effective_output_dir),
                output_index=args.output_index,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id, "output_dir": args.output_dir, "output_index": args.output_index},
                response_payload={"downloaded_path": str(path)},
                downloads=[{"type": "explicit_download", "path": str(path)}],
                effective_output_dir=str(path.parent),
            )
            print(f"[INFO] downloaded={path}")
            return 0

        if args.command == "pixel-gen-cancel":
            payload = pixel_gen_cancel(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "hd-gen-template-info":
            payload = hd_gen_template_info(
                api_base=args.api_base,
                api_key=args.api_key,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_public_json(payload))
            return 0

        if args.command == "hd-gen-submit":
            template_config = _parse_json_arg(args.template_config, name="template_config")
            request_payload = {
                "template_name": args.template_name,
                "requirement": args.requirement,
                "template_config": template_config,
                "job_name": args.job_name,
                "resolution": args.resolution,
                "aspect_ratio": args.aspect_ratio,
                "quality_mode": args.quality_mode,
                "remove_bg_method": args.remove_bg_method,
                "reference_file": args.reference_file,
                "reference_files": list(args.reference_files or []),
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            payload = submit_hd_gen(
                api_base=args.api_base,
                api_key=args.api_key,
                template_name=args.template_name,
                requirement=args.requirement,
                template_config=template_config,
                job_name=args.job_name,
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                quality_mode=args.quality_mode,
                remove_bg_method=args.remove_bg_method,
                reference_file=args.reference_file,
                reference_files=list(args.reference_files or []),
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "hd-gen-run":
            template_config = _parse_json_arg(args.template_config, name="template_config")
            slug_seed = args.job_name or args.requirement
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "template_name": args.template_name,
                "requirement": args.requirement,
                "template_config": template_config,
                "job_name": args.job_name,
                "resolution": args.resolution,
                "aspect_ratio": args.aspect_ratio,
                "quality_mode": args.quality_mode,
                "remove_bg_method": args.remove_bg_method,
                "reference_file": args.reference_file,
                "reference_files": list(args.reference_files or []),
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            submit_payload, final_payload = run_hd_gen(
                api_base=args.api_base,
                api_key=args.api_key,
                template_name=args.template_name,
                requirement=args.requirement,
                template_config=template_config,
                job_name=args.job_name,
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                quality_mode=args.quality_mode,
                remove_bg_method=args.remove_bg_method,
                reference_file=args.reference_file,
                reference_files=list(args.reference_files or []),
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="hd_gen",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "hd-gen-poll":
            payload = poll_hd_gen_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            downloads: list[dict[str, Any]] = []
            effective_poll_output_dir = Path(str(effective_output_dir)).expanduser()
            if str(payload.get("status") or "").strip().lower() in TERMINAL_JOB_STATUSES:
                effective_poll_output_dir, downloads = _save_run_outputs(
                    output_root=str(effective_output_dir),
                    slug_seed=args.api_job_id,
                    submit_payload={"api_job_id": args.api_job_id},
                    final_payload=payload,
                    timeout=args.timeout,
                    verify=verify,
                    api_key=args.api_key,
                    no_download=args.no_download,
                    workflow_id="hd_gen",
                )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=downloads,
                effective_output_dir=str(effective_poll_output_dir),
            )
            if downloads:
                print(f"[INFO] saved_dir={effective_poll_output_dir}")
            print(_format_json_for_display(payload))
            return 0

        if args.command == "hd-gen-history":
            payload = hd_gen_history(
                api_base=args.api_base,
                api_key=args.api_key,
                limit=args.limit,
                offset=args.offset,
                status=args.status,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"limit": args.limit, "offset": args.offset, "status": args.status},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "hd-gen-download":
            path = hd_gen_download(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                output_dir=args.output_dir or str(effective_output_dir),
                output_index=args.output_index,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id, "output_index": args.output_index},
                response_payload={"downloaded_path": str(path)},
                downloads=[{"type": "explicit_download", "path": str(path)}],
                effective_output_dir=str(path.parent),
            )
            print(f"[INFO] downloaded={path}")
            return 0

        if args.command == "hd-gen-cancel":
            payload = hd_gen_cancel(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "remove-background-submit":
            payload = submit_remove_background(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                mode=args.mode,
                quality=args.quality,
                prompt=args.prompt,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "image_file": args.image_file,
                    "mode": args.mode,
                    "quality": args.quality,
                    "prompt": args.prompt,
                },
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "remove-background-run":
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, args.prompt or Path(args.image_file).stem)}")
            submit_payload, final_payload = run_remove_background(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                mode=args.mode,
                quality=args.quality,
                prompt=args.prompt,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.prompt or Path(args.image_file).stem,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="remove_background",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "image_file": args.image_file,
                    "mode": args.mode,
                    "quality": args.quality,
                    "prompt": args.prompt,
                },
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "pixelate-submit":
            payload = submit_pixelate(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                pixel_size=args.pixel_size,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"image_file": args.image_file},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "pixelate-run":
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, Path(args.image_file).stem)}")
            submit_payload, final_payload = run_pixelate(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                pixel_size=args.pixel_size,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=Path(args.image_file).stem,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="pixelate",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"image_file": args.image_file},
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "self-loop-submit":
            payload = submit_pixel_gen_self_loop(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                job_name=args.job_name,
                resolution=args.resolution,
                mode=args.mode,
                direction=args.direction,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "image_file": args.image_file,
                    "mode": args.mode,
                    "direction": args.direction,
                },
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "self-loop-run":
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, args.job_name or Path(args.image_file).stem)}")
            submit_payload, final_payload = run_pixel_gen_self_loop(
                api_base=args.api_base,
                api_key=args.api_key,
                image_file=args.image_file,
                job_name=args.job_name,
                resolution=args.resolution,
                mode=args.mode,
                direction=args.direction,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.job_name or Path(args.image_file).stem,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="pixel_gen_self_loop",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={
                    "image_file": args.image_file,
                    "mode": args.mode,
                    "direction": args.direction,
                },
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command in {"sound-submit", "sfx-submit", "sound-effect-submit"}:
            request_payload = {
                "prompt": args.prompt,
                "duration": args.duration,
                "loop": args.loop,
                "sound_pack": args.sound_pack,
                "variants": args.variants,
                "count": args.count,
                "language": args.language,
            }
            payload = submit_sound_effect_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                duration=args.duration,
                loop=args.loop,
                sound_pack=args.sound_pack,
                variants=args.variants,
                count=args.count,
                language=args.language,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command in {"sound-run", "sfx-run", "sound-effect-run"}:
            slug_seed = args.prompt
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "prompt": args.prompt,
                "duration": args.duration,
                "loop": args.loop,
                "sound_pack": args.sound_pack,
                "variants": args.variants,
                "count": args.count,
                "language": args.language,
            }
            submit_payload, final_payload = run_sound_effect_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                duration=args.duration,
                loop=args.loop,
                sound_pack=args.sound_pack,
                variants=args.variants,
                count=args.count,
                language=args.language,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="elevenlabs_generator",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command in {
            "sound-poll",
            "sfx-poll",
            "sound-effect-poll",
            "texture-gen-poll",
            "tileset-gen-poll",
        } or args.command in MAP_WORKFLOW_POLL_COMMANDS or args.command in CHARACTER_MULTI_VIEW_POLL_COMMANDS or args.command in UI_GEN_POLL_COMMANDS:
            payload = poll_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            downloads: list[dict[str, Any]] = []
            poll_workflow_id = {
                "sound-poll": "elevenlabs_generator",
                "sfx-poll": "elevenlabs_generator",
                "sound-effect-poll": "elevenlabs_generator",
                "texture-gen-poll": "texture_gen",
                "tileset-gen-poll": "tileset_gen",
            }.get(args.command, "")
            if args.command in MAP_WORKFLOW_POLL_COMMANDS:
                poll_workflow_id = MAP_WORKFLOW_COMMANDS[args.command]
            elif args.command in CHARACTER_MULTI_VIEW_POLL_COMMANDS:
                poll_workflow_id = "character_multi_view_generator"
            elif args.command in UI_GEN_POLL_COMMANDS:
                poll_workflow_id = "general_ui_gen"
            effective_poll_output_dir = Path(str(effective_output_dir)).expanduser()
            if str(payload.get("status") or "").strip().lower() in TERMINAL_JOB_STATUSES:
                effective_poll_output_dir, downloads = _save_run_outputs(
                    output_root=str(effective_output_dir),
                    slug_seed=args.api_job_id,
                    submit_payload={"api_job_id": args.api_job_id},
                    final_payload=payload,
                    timeout=args.timeout,
                    verify=verify,
                    api_key=args.api_key,
                    no_download=args.no_download,
                    workflow_id=poll_workflow_id,
                )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=downloads,
                effective_output_dir=str(effective_poll_output_dir),
            )
            if downloads:
                print(f"[INFO] saved_dir={effective_poll_output_dir}")
            print(_format_json_for_display(payload))
            return 0

        if args.command in CHARACTER_MULTI_VIEW_SUBMIT_COMMANDS:
            request_payload = {
                "reference_image": args.reference_image,
                "mode": args.mode,
                "canvas_resolution": args.canvas_resolution,
                "direction_mode": args.direction_mode,
                "aspect_ratio": args.aspect_ratio,
                "remove_bg_method": args.remove_bg_method,
                "extra_constraint": args.extra_constraint,
                "output_size": args.output_size,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            payload = submit_character_multi_view_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                reference_image=args.reference_image,
                mode=args.mode,
                canvas_resolution=args.canvas_resolution,
                direction_mode=args.direction_mode,
                aspect_ratio=args.aspect_ratio,
                remove_bg_method=args.remove_bg_method,
                extra_constraint=args.extra_constraint,
                output_size=args.output_size,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command in CHARACTER_MULTI_VIEW_RUN_COMMANDS:
            slug_seed = f"{Path(args.reference_image).stem}_{args.mode}_multi_view"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "reference_image": args.reference_image,
                "mode": args.mode,
                "canvas_resolution": args.canvas_resolution,
                "direction_mode": args.direction_mode,
                "aspect_ratio": args.aspect_ratio,
                "remove_bg_method": args.remove_bg_method,
                "extra_constraint": args.extra_constraint,
                "output_size": args.output_size,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            submit_payload, final_payload = run_character_multi_view_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                reference_image=args.reference_image,
                mode=args.mode,
                canvas_resolution=args.canvas_resolution,
                direction_mode=args.direction_mode,
                aspect_ratio=args.aspect_ratio,
                remove_bg_method=args.remove_bg_method,
                extra_constraint=args.extra_constraint,
                output_size=args.output_size,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="character_multi_view_generator",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "texture-gen-submit":
            request_payload = {
                "prompt": args.prompt,
                "self_loop": args.self_loop,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            payload = submit_texture_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                self_loop=args.self_loop,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "texture-gen-run":
            slug_seed = args.prompt or "texture"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "prompt": args.prompt,
                "self_loop": args.self_loop,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            submit_payload, final_payload = run_texture_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                self_loop=args.self_loop,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="texture_gen",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "tileset-gen-submit":
            request_payload = {
                "prompt": args.prompt,
                "terrain_mode": args.terrain_mode,
                "foreground_texture": args.foreground_texture,
                "background_texture": args.background_texture,
                "remove_bg_method": args.remove_bg_method,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            payload = submit_tileset_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                terrain_mode=args.terrain_mode,
                foreground_texture=args.foreground_texture,
                background_texture=args.background_texture,
                remove_bg_method=args.remove_bg_method,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "tileset-gen-run":
            slug_seed = args.prompt or "tileset"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "prompt": args.prompt,
                "terrain_mode": args.terrain_mode,
                "foreground_texture": args.foreground_texture,
                "background_texture": args.background_texture,
                "remove_bg_method": args.remove_bg_method,
                "project_id": args.project_id,
                "thread_id": args.thread_id,
            }
            submit_payload, final_payload = run_tileset_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                terrain_mode=args.terrain_mode,
                foreground_texture=args.foreground_texture,
                background_texture=args.background_texture,
                remove_bg_method=args.remove_bg_method,
                project_id=args.project_id,
                thread_id=args.thread_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="tileset_gen",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command in UI_GEN_SUBMIT_COMMANDS:
            reference_images = list(args.reference_image or [])
            request_payload = {
                "prompt": args.prompt,
                "reference_images": reference_images,
                "resolution": args.resolution,
                "aspect_ratio": args.aspect_ratio,
                "quality": args.quality,
                "remove_bg_method": args.remove_bg_method,
                "generation_mode": args.generation_mode,
            }
            payload = submit_ui_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                reference_images=reference_images,
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                quality=args.quality,
                remove_bg_method=args.remove_bg_method,
                generation_mode=args.generation_mode,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command in UI_GEN_RUN_COMMANDS:
            reference_images = list(args.reference_image or [])
            slug_seed = args.prompt or "ui-gen"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "prompt": args.prompt,
                "reference_images": reference_images,
                "resolution": args.resolution,
                "aspect_ratio": args.aspect_ratio,
                "quality": args.quality,
                "remove_bg_method": args.remove_bg_method,
                "generation_mode": args.generation_mode,
            }
            submit_payload, final_payload = run_ui_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                reference_images=reference_images,
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                quality=args.quality,
                remove_bg_method=args.remove_bg_method,
                generation_mode=args.generation_mode,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="general_ui_gen",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command in MAP_WORKFLOW_COMMANDS and args.command not in MAP_WORKFLOW_POLL_COMMANDS:
            workflow_id = MAP_WORKFLOW_COMMANDS[args.command]
            reference_images = list(getattr(args, "reference_image", []) or [])
            project_id = getattr(args, "project_id", None)
            thread_id = getattr(args, "thread_id", None)
            request_payload = {
                "workflow_id": workflow_id,
                "prompt": args.prompt,
                "reference_images": reference_images,
                "mode": args.mode,
                "remove_bg_method": getattr(args, "remove_bg_method", ""),
                "template": getattr(args, "template", ""),
                "style_name": getattr(args, "style_name", ""),
                "style_description": getattr(args, "style_description", ""),
                "project_id": project_id,
                "thread_id": thread_id,
            }
            if args.command.endswith("-submit"):
                payload = submit_map_workflow(
                    api_base=args.api_base,
                    api_key=args.api_key,
                    workflow_id=workflow_id,
                    prompt=args.prompt,
                    reference_images=reference_images,
                    mode=args.mode,
                    remove_bg_method=getattr(args, "remove_bg_method", ""),
                    template=getattr(args, "template", ""),
                    style_name=getattr(args, "style_name", ""),
                    style_description=getattr(args, "style_description", ""),
                    project_id=project_id,
                    thread_id=thread_id,
                    timeout=args.timeout,
                    verify=verify,
                )
                _write_meta(
                    run_dir=run_dir,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    args=args,
                    request_payload=request_payload,
                    response_payload=payload,
                    downloads=[],
                    effective_output_dir=str(effective_output_dir),
                )
                print(_format_json_for_display(payload))
                return 0

            slug_seed = args.prompt or workflow_id
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            submit_payload, final_payload = run_map_workflow(
                api_base=args.api_base,
                api_key=args.api_key,
                workflow_id=workflow_id,
                label=args.command.removesuffix("-run"),
                prompt=args.prompt,
                reference_images=reference_images,
                mode=args.mode,
                remove_bg_method=getattr(args, "remove_bg_method", ""),
                template=getattr(args, "template", ""),
                style_name=getattr(args, "style_name", ""),
                style_description=getattr(args, "style_description", ""),
                project_id=project_id,
                thread_id=thread_id,
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id=workflow_id,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(
                _format_public_json(
                    _local_run_summary(
                        submit_payload=submit_payload,
                        final_payload=final_payload,
                        downloads=downloads,
                    )
                )
            )
            return 0

        if args.command == "music-submit":
            request_payload = {
                "prompt": args.prompt,
                "audio_generate": args.audio_generate,
                "demo": args.demo,
                "reference_images": list(args.reference_image or []),
            }
            payload = submit_music_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                audio_generate=args.audio_generate,
                demo=args.demo,
                reference_images=list(args.reference_image or []),
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "music-run":
            slug_seed = args.prompt or (Path(args.reference_image[0]).stem if args.reference_image else "music")
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            request_payload = {
                "prompt": args.prompt,
                "audio_generate": args.audio_generate,
                "demo": args.demo,
                "reference_images": list(args.reference_image or []),
            }
            submit_payload, final_payload = run_music_generator(
                api_base=args.api_base,
                api_key=args.api_key,
                prompt=args.prompt,
                audio_generate=args.audio_generate,
                demo=args.demo,
                reference_images=list(args.reference_image or []),
                timeout=args.timeout,
                max_wait=args.max_wait,
                poll_interval=args.poll_interval,
                verify=verify,
            )
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="music_generator",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload=request_payload,
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "music-poll":
            payload = poll_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            downloads: list[dict[str, Any]] = []
            effective_poll_output_dir = Path(str(effective_output_dir)).expanduser()
            if str(payload.get("status") or "").strip().lower() in TERMINAL_JOB_STATUSES:
                effective_poll_output_dir, downloads = _save_run_outputs(
                    output_root=str(effective_output_dir),
                    slug_seed=args.api_job_id,
                    submit_payload={"api_job_id": args.api_job_id},
                    final_payload=payload,
                    timeout=args.timeout,
                    verify=verify,
                    api_key=args.api_key,
                    no_download=args.no_download,
                    workflow_id="music_generator",
                )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=downloads,
                effective_output_dir=str(effective_poll_output_dir),
            )
            if downloads:
                print(f"[INFO] saved_dir={effective_poll_output_dir}")
            print(_format_json_for_display(payload))
            return 0

        if args.command == "credits-balance":
            payload = get_credits_balance(
                api_base=args.api_base,
                api_key=args.api_key,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "animate-submit":
            payload = submit_animate(
                api_base=args.api_base,
                api_key=args.api_key,
                image_data_url=image_file_to_data_url(args.image_file),
                prompt=args.prompt,
                is_pixel=args.is_pixel,
                output_frames=args.output_frames,
                output_format=args.output_format,
                animation_type=args.animation_type,
                remove_bg_method=args.remove_bg_method,
                timeout=args.timeout,
                verify=verify,
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"image_file": args.image_file, "prompt": args.prompt, "is_pixel": args.is_pixel},
                response_payload=payload,
                downloads=[],
                effective_output_dir=str(effective_output_dir),
            )
            print(_format_json_for_display(payload))
            return 0

        if args.command == "animate-run":
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, args.prompt or Path(args.image_file).stem)}")
            submit_payload = submit_animate(
                api_base=args.api_base,
                api_key=args.api_key,
                image_data_url=image_file_to_data_url(args.image_file),
                prompt=args.prompt,
                is_pixel=args.is_pixel,
                output_frames=args.output_frames,
                output_format=args.output_format,
                animation_type=args.animation_type,
                remove_bg_method=args.remove_bg_method,
                timeout=args.timeout,
                verify=verify,
            )
            api_job_id = str(submit_payload.get("api_job_id") or "").strip()
            if not api_job_id:
                raise RuntimeError("animate submit response missing api_job_id")
            print(f"[INFO] submitted api_job_id={api_job_id}")
            try:
                final_payload = wait_animate_job(
                    api_base=args.api_base,
                    api_key=args.api_key,
                    api_job_id=api_job_id,
                    timeout=args.timeout,
                    max_wait=args.max_wait,
                    poll_interval=args.poll_interval,
                    verify=verify,
                )
            except (RuntimeError, TimeoutError) as exc:
                _write_meta(
                    run_dir=run_dir,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(timespec="seconds"),
                    args=args,
                    request_payload={"image_file": args.image_file, "prompt": args.prompt, "is_pixel": args.is_pixel},
                    response_payload={"submit": submit_payload},
                    downloads=[],
                    effective_output_dir=str(effective_output_dir),
                    error=str(exc),
                )
                print(f"[WARN] animate submitted but polling did not complete: {exc}")
                print(_format_json_for_display(submit_payload))
                return 1
            output_dir, downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=args.prompt or Path(args.image_file).stem,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="animate",
            )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"image_file": args.image_file, "prompt": args.prompt, "is_pixel": args.is_pixel},
                response_payload={"submit": submit_payload, "final": final_payload},
                downloads=downloads,
                effective_output_dir=str(output_dir),
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "keyframes-run":
            slug_seed = args.prompt or "keyframes"
            print(f"[INFO] planned_output_dir={_predict_saved_dir(effective_output_dir, slug_seed)}")
            submit_payload = submit_keyframes(
                api_base=args.api_base,
                api_key=args.api_key,
                keyframe_specs=list(args.keyframe or []),
                prompt=args.prompt,
                total_frames=args.total_frames,
                output_format=args.output_format,
                animation_type=args.animation_type,
                remove_bg_method=args.remove_bg_method,
                timeout=args.timeout,
                verify=verify,
            )
            api_job_id = str(submit_payload.get("api_job_id") or "").strip()
            if not api_job_id:
                raise RuntimeError("keyframes submit response missing api_job_id")
            print(f"[INFO] submitted api_job_id={api_job_id}")
            try:
                final_payload = wait_animate_job(
                    api_base=args.api_base,
                    api_key=args.api_key,
                    api_job_id=api_job_id,
                    timeout=args.timeout,
                    max_wait=args.max_wait,
                    poll_interval=args.poll_interval,
                    verify=verify,
                )
            except (RuntimeError, TimeoutError) as exc:
                print(f"[WARN] keyframes submitted but polling did not complete: {exc}")
                print(_format_json_for_display(submit_payload))
                return 1
            output_dir, _downloads = _save_run_outputs(
                output_root=str(effective_output_dir),
                slug_seed=slug_seed,
                submit_payload=submit_payload,
                final_payload=final_payload,
                timeout=args.timeout,
                verify=verify,
                api_key=args.api_key,
                no_download=args.no_download,
                workflow_id="animate",
            )
            print(f"[INFO] saved_dir={output_dir}")
            print(_format_json_for_display(final_payload))
            return 0

        if args.command == "animate-poll":
            payload = poll_animate_job(
                api_base=args.api_base,
                api_key=args.api_key,
                api_job_id=args.api_job_id,
                timeout=args.timeout,
                verify=verify,
            )
            downloads: list[dict[str, Any]] = []
            effective_poll_output_dir = Path(str(effective_output_dir)).expanduser()
            if str(payload.get("status") or "").strip().lower() in SUCCESS_ANIMATE_STATUSES:
                effective_poll_output_dir, downloads = _save_run_outputs(
                    output_root=str(effective_output_dir),
                    slug_seed=args.api_job_id,
                    submit_payload={"api_job_id": args.api_job_id},
                    final_payload=payload,
                    timeout=args.timeout,
                    verify=verify,
                    api_key=args.api_key,
                    no_download=args.no_download,
                    workflow_id="animate",
                )
            _write_meta(
                run_dir=run_dir,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                args=args,
                request_payload={"api_job_id": args.api_job_id},
                response_payload=payload,
                downloads=downloads,
                effective_output_dir=str(effective_poll_output_dir),
            )
            if downloads:
                print(f"[INFO] saved_dir={effective_poll_output_dir}")
            print(_format_json_for_display(payload))
            return 0

        print(f"[ERROR] unknown command: {args.command}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as exc:
        _write_meta(
            run_dir=run_dir,
            started_at=started_at,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            args=args,
            request_payload={},
            response_payload=None,
            downloads=[],
            effective_output_dir=str(effective_output_dir),
            error=str(exc),
        )
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
