#!/usr/bin/env python3
"""Build a self-contained interactive map preview from local tile images."""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


SUPPORTED_MODES = ("isometric", "hex", "dual-grid", "iso-dual-grid")
MIME_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_EMBEDDED_BYTES = 64 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create an interactive HTML map preview with local tile images embedded. "
            "The generated page opens with the assets already loaded."
        )
    )
    parser.add_argument("--mode", choices=SUPPORTED_MODES, required=True)
    parser.add_argument(
        "--image",
        action="append",
        type=Path,
        required=True,
        help="Local PNG or WebP path. Repeat for multiple isometric or hex tiles.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output .html path.")
    parser.add_argument("--columns", type=int, default=8, choices=range(2, 33))
    parser.add_argument("--rows", type=int, default=6, choices=range(2, 33))
    parser.add_argument("--zoom", type=int, default=1, choices=range(1, 5))
    parser.add_argument("--grid", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def encode_image(path: Path) -> tuple[dict[str, str], int]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Image does not exist or is not a file: {path}")
    mime_type = MIME_TYPES.get(resolved.suffix.lower())
    if not mime_type:
        raise ValueError(f"Only PNG and WebP images are supported: {path}")
    content = resolved.read_bytes()
    encoded = base64.b64encode(content).decode("ascii")
    return {
        "name": resolved.name,
        "src": f"data:{mime_type};base64,{encoded}",
    }, len(content)


def safe_json_for_script(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def build_preview(args: argparse.Namespace) -> dict[str, object]:
    if args.output.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("--output must use an .html or .htm extension")
    if args.mode in {"dual-grid", "iso-dual-grid"} and len(args.image) != 1:
        raise ValueError(f"{args.mode} requires exactly one 4x4 atlas image")

    skill_root = Path(__file__).resolve().parent.parent
    template_path = skill_root / "assets" / "map-tile-layout-demo.html"
    helper_path = skill_root / "scripts" / "map-tile-layout.js"
    html = template_path.read_text(encoding="utf-8")
    helper = helper_path.read_text(encoding="utf-8")

    images: list[dict[str, str]] = []
    total_bytes = 0
    for path in args.image:
        image, byte_count = encode_image(path)
        images.append(image)
        total_bytes += byte_count
    if total_bytes > MAX_EMBEDDED_BYTES:
        raise ValueError(
            f"Embedded images total {total_bytes} bytes; limit is {MAX_EMBEDDED_BYTES} bytes"
        )

    preload = safe_json_for_script(
        {
            "mode": args.mode,
            "columns": args.columns,
            "rows": args.rows,
            "zoom": args.zoom,
            "grid": args.grid,
            "images": images,
        }
    )
    external_helper = '<script src="../scripts/map-tile-layout.js"></script>'
    if external_helper not in html:
        raise RuntimeError("Preview template is missing the layout helper script tag")
    html = html.replace(external_helper, f"<script>\n{helper}\n</script>", 1)
    html, replacement_count = re.subn(
        r'(<script id="meowa-map-preload" type="application/json">).*?(</script>)',
        lambda match: f"{match.group(1)}{preload}{match.group(2)}",
        html,
        count=1,
        flags=re.DOTALL,
    )
    if replacement_count != 1:
        raise RuntimeError("Preview template is missing the preload data element")

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return {
        "output": str(output),
        "mode": args.mode,
        "image_count": len(images),
        "embedded_bytes": total_bytes,
        "html_bytes": output.stat().st_size,
    }


def main() -> int:
    args = parse_args()
    try:
        result = build_preview(args)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"error: {error}") from error
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
