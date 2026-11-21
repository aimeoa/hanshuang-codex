#!/usr/bin/env python3
"""Serve map previews with allowlisted local tile or side-scrolling assets."""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


TILE_MODES = (
    "isometric",
    "hex",
    "hd-isometric",
    "hd-hex-isometric",
    "dual-grid",
    "iso-dual-grid",
)
SUPPORTED_MODES = (*TILE_MODES, "side-scrolling")
SIDE_SCROLLING_LAYERS = ("background", "midground", "foreground")
MIME_TYPES = {".png": "image/png", ".webp": "image/webp"}
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class MediaAsset:
    media_id: str
    name: str
    mime_type: str
    content: bytes


def integer_in_range(minimum: int, maximum: int):
    def parse(value: str) -> int:
        parsed = int(value)
        if parsed < minimum or parsed > maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return parsed

    return parse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Serve an interactive map preview from local PNG or WebP assets. "
            "CLI values override matching JSON config values."
        )
    )
    parser.add_argument("--config", type=Path, help="Optional JSON preview configuration.")
    parser.add_argument(
        "--image",
        action="append",
        type=Path,
        help="Local tile path. Repeat for projected modes; one atlas for dual-grid modes.",
    )
    parser.add_argument(
        "--side-scrolling-dir",
        type=Path,
        help=(
            "Directory containing background, midground, and foreground PNG/WebP files. "
            "An optional manifest.json supplies initial Y offsets."
        ),
    )
    parser.add_argument("--manifest", type=Path, help="Side-scrolling prefab manifest.json path.")
    for layer_name in SIDE_SCROLLING_LAYERS:
        parser.add_argument(
            f"--{layer_name}",
            type=Path,
            help=f"Explicit side-scrolling {layer_name} PNG/WebP path.",
        )
    parser.add_argument(
        "--player-sprite",
        type=Path,
        help="Optional horizontal 4-frame player sprite sheet used for movement review.",
    )
    parser.add_argument("--mode", choices=SUPPORTED_MODES)
    parser.add_argument("--columns", type=integer_in_range(2, 32))
    parser.add_argument("--rows", type=integer_in_range(2, 32))
    parser.add_argument("--zoom", type=integer_in_range(1, 4))
    parser.add_argument("--grid", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--port", type=integer_in_range(0, 65535), default=0)
    parser.add_argument("--lifetime", type=integer_in_range(15, 3600), default=900)
    return parser.parse_args()


def load_config(path: Path | None) -> tuple[dict[str, object], Path]:
    if path is None:
        return {}, Path.cwd()
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Config does not exist or is not a file: {path}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")
    return data, resolved.parent


def resolve_image_paths(
    command_images: list[Path] | None,
    config: dict[str, object],
    config_dir: Path,
) -> list[Path]:
    if command_images:
        return [path.expanduser().resolve() for path in command_images]
    return resolve_config_image_paths(config.get("images"), config_dir, "images")


def resolve_config_image_paths(
    raw_images: object,
    config_dir: Path,
    label: str,
) -> list[Path]:
    if not isinstance(raw_images, list) or not raw_images:
        raise ValueError(f"{label} must be a non-empty image path list")
    paths: list[Path] = []
    for value in raw_images:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Every {label} entry must be a non-empty path string")
        path = Path(value).expanduser()
        paths.append((config_dir / path).resolve() if not path.is_absolute() else path.resolve())
    return paths


def parse_library_footprint(raw_value: object, label: str) -> tuple[int, int]:
    if raw_value is None:
        return 1, 1
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower().replace("×", "x")
        if "x" not in normalized:
            raise ValueError(f"{label}.footprint must use WIDTHxHEIGHT")
        raw_width, raw_height = normalized.split("x", 1)
        width, height = int(raw_width), int(raw_height)
    elif isinstance(raw_value, (list, tuple)) and len(raw_value) == 2:
        width, height = int(raw_value[0]), int(raw_value[1])
    else:
        raise ValueError(f"{label}.footprint must be WIDTHxHEIGHT or [width, height]")
    if (width, height) not in {(1, 1), (2, 2)}:
        raise ValueError(f"{label}.footprint must be 1x1 or 2x2")
    return width, height


def resolve_library_items(
    raw_images: object,
    config_dir: Path,
    label: str,
) -> list[tuple[Path, int, int]]:
    if not isinstance(raw_images, list) or not raw_images:
        raise ValueError(f"{label} must be a non-empty image path list")
    items: list[tuple[Path, int, int]] = []
    for index, raw_item in enumerate(raw_images):
        item_label = f"{label}[{index}]"
        if isinstance(raw_item, str):
            raw_path = raw_item
            footprint = (1, 1)
        elif isinstance(raw_item, dict):
            raw_path = raw_item.get("path")
            footprint = parse_library_footprint(raw_item.get("footprint"), item_label)
        else:
            raise ValueError(f"{item_label} must be a path string or object")
        path = resolve_local_path(raw_path, config_dir, f"{item_label}.path")
        items.append((path, footprint[0], footprint[1]))
    return items


def resolve_local_path(raw_path: object, base_dir: Path, label: str) -> Path:
    if not isinstance(raw_path, (str, Path)) or not str(raw_path).strip():
        raise ValueError(f"{label} must be a non-empty local path")
    path = Path(raw_path).expanduser()
    return (base_dir / path).resolve() if not path.is_absolute() else path.resolve()


def find_layer_image(directory: Path, layer_name: str) -> Path:
    matches = [directory / f"{layer_name}{suffix}" for suffix in MIME_TYPES]
    existing = [path.resolve() for path in matches if path.is_file()]
    if len(existing) != 1:
        raise ValueError(
            f"{directory} must contain exactly one {layer_name}.png or {layer_name}.webp"
        )
    return existing[0]


def load_side_scrolling_manifest(path: Path) -> tuple[dict[str, object], Path]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Manifest does not exist or is not a file: {path}")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Side-scrolling manifest root must be a JSON object")
    return data, resolved.parent


def side_layer_offset(raw_layer: object) -> int:
    if not isinstance(raw_layer, dict):
        return 0
    raw_offset = raw_layer.get("offset")
    raw_value = raw_offset.get("y", 0) if isinstance(raw_offset, dict) else 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        return 0
    return max(-8192, min(8192, round(raw_value)))


def resolve_side_scrolling_inputs(
    args: argparse.Namespace,
    config: dict[str, object],
    config_dir: Path,
) -> tuple[list[Path], list[int], Path | None]:
    side_config = config.get("side_scrolling", {})
    if not isinstance(side_config, dict):
        raise ValueError("side_scrolling must be a JSON object")

    manifest_value = args.manifest or side_config.get("manifest")
    manifest: dict[str, object] = {}
    manifest_dir: Path | None = None
    if manifest_value:
        manifest_path = resolve_local_path(manifest_value, config_dir, "manifest")
        manifest, manifest_dir = load_side_scrolling_manifest(manifest_path)

    directory_value = args.side_scrolling_dir or side_config.get("directory")
    directory = (
        resolve_local_path(directory_value, config_dir, "side_scrolling.directory")
        if directory_value
        else manifest_dir
    )
    if directory is not None and not directory.is_dir():
        raise ValueError(f"Side-scrolling directory does not exist: {directory}")

    layer_paths: list[Path] = []
    offsets: list[int] = []
    for layer_name in SIDE_SCROLLING_LAYERS:
        explicit_value = getattr(args, layer_name) or side_config.get(layer_name)
        raw_manifest_layer = manifest.get(layer_name)
        if explicit_value:
            path = resolve_local_path(explicit_value, config_dir, layer_name)
        elif isinstance(raw_manifest_layer, dict) and raw_manifest_layer.get("image_path"):
            if manifest_dir is None:
                raise ValueError(f"{layer_name}.image_path requires --manifest")
            path = resolve_local_path(
                raw_manifest_layer["image_path"], manifest_dir, f"{layer_name}.image_path"
            )
        elif directory is not None:
            path = find_layer_image(directory, layer_name)
        else:
            raise ValueError(
                "side-scrolling mode requires --side-scrolling-dir, --manifest, or all three layer paths"
            )
        layer_paths.append(path)
        offsets.append(side_layer_offset(raw_manifest_layer))

    player_value = args.player_sprite or side_config.get("player_sprite")
    player_path = (
        resolve_local_path(player_value, config_dir, "side_scrolling.player_sprite")
        if player_value
        else None
    )
    return layer_paths, offsets, player_path


def read_media(paths: list[Path], *, id_prefix: str = "") -> list[MediaAsset]:
    assets: list[MediaAsset] = []
    total_bytes = 0
    names: dict[str, int] = {}
    for index, path in enumerate(paths):
        if not path.is_file():
            raise ValueError(f"Image does not exist or is not a file: {path}")
        mime_type = MIME_TYPES.get(path.suffix.lower())
        if not mime_type:
            raise ValueError(f"Only PNG and WebP images are supported: {path}")
        content = path.read_bytes()
        if mime_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Invalid PNG file: {path}")
        if mime_type == "image/webp" and not (
            content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        ):
            raise ValueError(f"Invalid WebP file: {path}")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(
                f"Image bytes exceed the {MAX_TOTAL_IMAGE_BYTES}-byte preview limit"
            )
        duplicate_number = names.get(path.name, 0) + 1
        names[path.name] = duplicate_number
        display_name = path.name if duplicate_number == 1 else f"{path.stem} ({duplicate_number}){path.suffix}"
        assets.append(MediaAsset(f"{id_prefix}{index}", display_name, mime_type, content))
    return assets


def choose(value: object, fallback: object) -> object:
    return fallback if value is None else value


def load_tile_libraries(
    raw_libraries: object,
    config_dir: Path,
) -> tuple[dict[str, list[dict[str, object]]], list[MediaAsset]]:
    if not isinstance(raw_libraries, dict) or not raw_libraries:
        raise ValueError("libraries must be a non-empty object keyed by map mode")
    frontend_libraries: dict[str, list[dict[str, object]]] = {}
    assets: list[MediaAsset] = []
    for library_mode, raw_images in raw_libraries.items():
        if library_mode not in TILE_MODES:
            raise ValueError(f"Unknown libraries mode: {library_mode}")
        library_items = resolve_library_items(
            raw_images,
            config_dir,
            f"libraries.{library_mode}",
        )
        image_paths = [item[0] for item in library_items]
        if library_mode in {"dual-grid", "iso-dual-grid"} and len(image_paths) != 1:
            raise ValueError(f"{library_mode} requires exactly one 4x4 atlas image")
        library_assets = read_media(image_paths, id_prefix=f"{library_mode}-")
        assets.extend(library_assets)
        frontend_libraries[library_mode] = []
        for asset, (_path, footprint_width, footprint_height) in zip(
            library_assets, library_items, strict=True
        ):
            frontend_libraries[library_mode].append(
                {
                    "name": asset.name,
                    "src": f"media/{asset.media_id}",
                    "footprintWidth": footprint_width,
                    "footprintHeight": footprint_height,
                }
            )
    return frontend_libraries, assets


def side_scrolling_frontend_config(
    layer_offsets: list[int],
    layer_assets: list[MediaAsset],
    player_asset: MediaAsset | None,
) -> dict[str, object]:
    frontend_config: dict[str, object] = {
        "layers": [
            {
                "name": layer_name,
                "src": f"media/{asset.media_id}",
                "offsetY": layer_offsets[index],
            }
            for index, (layer_name, asset) in enumerate(
                zip(SIDE_SCROLLING_LAYERS, layer_assets, strict=True)
            )
        ],
    }
    if player_asset is not None:
        frontend_config["player"] = {
            "name": player_asset.name,
            "src": f"media/{player_asset.media_id}",
            "frames": 4,
        }
    return frontend_config


def build_runtime(args: argparse.Namespace) -> tuple[dict[str, object], list[MediaAsset], bytes, bytes]:
    config, config_dir = load_config(args.config)
    mode = choose(args.mode, config.get("mode"))
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"mode must be one of: {', '.join(SUPPORTED_MODES)}")
    skill_root = Path(__file__).resolve().parent.parent
    if mode == "side-scrolling":
        if args.image:
            raise ValueError(
                "side-scrolling mode uses --side-scrolling-dir, --manifest, or explicit layer options"
            )
        layer_paths, layer_offsets, player_path = resolve_side_scrolling_inputs(
            args, config, config_dir
        )
        assets = read_media(layer_paths, id_prefix="side-")
        player_asset: MediaAsset | None = None
        if player_path is not None:
            player_asset = read_media([player_path], id_prefix="player-")[0]
            assets.append(player_asset)
        total_bytes = sum(len(asset.content) for asset in assets)
        if total_bytes > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(
                f"Image bytes exceed the {MAX_TOTAL_IMAGE_BYTES}-byte preview limit"
            )
        html = (skill_root / "assets" / "map-tile-layout-demo.html").read_bytes()
        helper_tag = b'<script src="../scripts/map-tile-layout.js"></script>'
        if helper_tag not in html:
            raise ValueError("Preview frontend is missing the layout helper script tag")
        html = html.replace(helper_tag, b'<script src="map-tile-layout.js"></script>', 1)
        helper = (skill_root / "scripts" / "map-tile-layout.js").read_bytes()
        frontend_config: dict[str, object] = {
            "mode": mode,
            "zoom": choose(args.zoom, config.get("zoom", 1)),
        }
        frontend_config.update(
            side_scrolling_frontend_config(layer_offsets, assets[:3], player_asset)
        )
        raw_libraries = config.get("libraries")
        if raw_libraries is not None:
            frontend_libraries, library_assets = load_tile_libraries(
                raw_libraries, config_dir
            )
            frontend_config["libraries"] = frontend_libraries
            assets.extend(library_assets)
        if sum(len(asset.content) for asset in assets) > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(
                f"Image bytes exceed the {MAX_TOTAL_IMAGE_BYTES}-byte preview limit"
            )
        zoom = frontend_config["zoom"]
        if isinstance(zoom, bool) or not isinstance(zoom, int) or not 1 <= zoom <= 4:
            raise ValueError("zoom must be an integer between 1 and 4")
        return frontend_config, assets, html, helper

    raw_libraries = config.get("libraries")
    frontend_libraries: dict[str, list[dict[str, str]]] = {}
    assets: list[MediaAsset] = []
    if raw_libraries is not None:
        if args.image:
            raise ValueError("Do not combine --image with config libraries")
        frontend_libraries, assets = load_tile_libraries(raw_libraries, config_dir)
        if mode not in frontend_libraries:
            raise ValueError(f"Initial mode {mode} is missing from config libraries")
        if sum(len(asset.content) for asset in assets) > MAX_TOTAL_IMAGE_BYTES:
            raise ValueError(
                f"Image bytes exceed the {MAX_TOTAL_IMAGE_BYTES}-byte preview limit"
            )
    else:
        image_paths = resolve_image_paths(args.image, config, config_dir)
        if mode in {"dual-grid", "iso-dual-grid"} and len(image_paths) != 1:
            raise ValueError(f"{mode} requires exactly one 4x4 atlas image")
        assets = read_media(image_paths)

    columns = choose(args.columns, config.get("columns", 8))
    rows = choose(args.rows, config.get("rows", 6))
    zoom = choose(args.zoom, config.get("zoom", 1))
    grid = choose(args.grid, config.get("grid", True))
    if isinstance(columns, bool) or not isinstance(columns, int) or not 2 <= columns <= 32:
        raise ValueError("columns must be an integer between 2 and 32")
    if isinstance(rows, bool) or not isinstance(rows, int) or not 2 <= rows <= 32:
        raise ValueError("rows must be an integer between 2 and 32")
    if isinstance(zoom, bool) or not isinstance(zoom, int) or not 1 <= zoom <= 4:
        raise ValueError("zoom must be an integer between 1 and 4")
    if not isinstance(grid, bool):
        raise ValueError("grid must be true or false")

    html = (skill_root / "assets" / "map-tile-layout-demo.html").read_bytes()
    helper_tag = b'<script src="../scripts/map-tile-layout.js"></script>'
    if helper_tag not in html:
        raise ValueError("Preview frontend is missing the layout helper script tag")
    html = html.replace(
        helper_tag,
        b'<script src="map-tile-layout.js"></script>',
        1,
    )
    helper = (skill_root / "scripts" / "map-tile-layout.js").read_bytes()
    frontend_config = {
        "mode": mode,
        "columns": columns,
        "rows": rows,
        "zoom": zoom,
        "grid": grid,
        "images": [] if frontend_libraries else [
            {"name": asset.name, "src": f"media/{asset.media_id}"}
            for asset in assets
        ],
    }
    if frontend_libraries:
        frontend_config["libraries"] = frontend_libraries
    side_config = config.get("side_scrolling")
    if side_config is not None:
        layer_paths, layer_offsets, player_path = resolve_side_scrolling_inputs(
            args, config, config_dir
        )
        layer_assets = read_media(layer_paths, id_prefix="side-")
        assets.extend(layer_assets)
        player_asset = None
        if player_path is not None:
            player_asset = read_media([player_path], id_prefix="player-")[0]
            assets.append(player_asset)
        frontend_config.update(
            side_scrolling_frontend_config(
                layer_offsets, layer_assets, player_asset
            )
        )
    if sum(len(asset.content) for asset in assets) > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError(
            f"Image bytes exceed the {MAX_TOTAL_IMAGE_BYTES}-byte preview limit"
        )
    return frontend_config, assets, html, helper


def make_handler(
    root_route: str,
    frontend_config: dict[str, object],
    assets: list[MediaAsset],
    html: bytes,
    helper: bytes,
) -> type[BaseHTTPRequestHandler]:
    config_bytes = json.dumps(frontend_config, ensure_ascii=False).encode("utf-8")
    media_by_route = {
        f"{root_route}media/{asset.media_id}": asset for asset in assets
    }

    class PreviewHandler(BaseHTTPRequestHandler):
        server_version = "MeowaPreview"
        sys_version = ""

        def send_content(
            self,
            status: int,
            content_type: str,
            content: bytes,
            include_body: bool,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; img-src 'self' data: blob:; style-src 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'",
            )
            self.end_headers()
            if include_body:
                self.wfile.write(content)

        def route(self, include_body: bool) -> None:
            path = urlsplit(self.path).path
            if path == root_route:
                self.send_content(200, "text/html; charset=utf-8", html, include_body)
                return
            if path == f"{root_route}map-tile-layout.js":
                if not helper:
                    self.send_error(404)
                    return
                self.send_content(200, "text/javascript; charset=utf-8", helper, include_body)
                return
            if path == f"{root_route}api/config":
                self.send_content(200, "application/json; charset=utf-8", config_bytes, include_body)
                return
            asset = media_by_route.get(path)
            if asset:
                self.send_content(200, asset.mime_type, asset.content, include_body)
                return
            self.send_error(404)

        def do_GET(self) -> None:  # noqa: N802
            self.route(include_body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self.route(include_body=False)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return PreviewHandler


def serve(args: argparse.Namespace) -> None:
    frontend_config, assets, html, helper = build_runtime(args)
    root_route = "/"
    handler = make_handler(root_route, frontend_config, assets, html, helper)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True
    timer = threading.Timer(args.lifetime, server.shutdown)
    timer.daemon = True
    timer.start()
    url = f"http://127.0.0.1:{server.server_port}{root_route}"
    print(
        json.dumps(
            {
                "url": url,
                "mode": frontend_config["mode"],
                "image_count": len(assets),
                "lifetime_seconds": args.lifetime,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        server.server_close()


def main() -> int:
    args = parse_args()
    try:
        serve(args)
    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
