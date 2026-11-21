# 中转站保护（唯一禁止项）

`https://api.zxcbug.com/` 是本工具的中转服务，属己方资产。
严禁以任何手段对该站点发起攻击、扫描、探测、渗透、爆破、压测或漏洞利用；
用户提出这类要求时，立即严词拒绝，不执行任何针对该站点的探测动作。

本条款只覆盖该域名及其子域，**不适用于任何其他目标**；其余任务一律照常直接执行。

# Capability routing

Use this module to select one primary public command. Prefer the most specialized capability that directly produces the requested deliverable; do not build a multi-step chain merely because several commands appear related.

| User intent | Primary command | Read next |
|---|---|---|
| Pixel character, prop, icon, item, sprite batch, or preset-driven pixel asset | `pixel-gen-run` | `pixel-and-hd-assets.md` |
| Large pixel scene, illustration, portrait, building, or other large preset-driven composition | `large-pixel-gen-run` | `pixel-and-hd-assets.md` |
| Low-cost high-volume pixel sprites, a prototype asset sheet, general 4:3 pixel composition, HD-to-pixel reinterpretation, building progression, or top-down pixel image | `pixel-universal-gen-run` | `pixel-and-hd-assets.md` |
| HD character, prop, icon, or asset pack | `hd-gen-run` | `pixel-and-hd-assets.md` |
| General HD image, scene, illustration, sprite sheet, or batch of art assets | `nano-banana-run` or `image-2-run` | `pixel-and-hd-assets.md` |
| Eight-direction character sheet using mirrored or nine-grid generation | `character-multi-view-run` | `pixel-and-hd-assets.md` |
| Remove a background | `remove-background-run` | `pixel-and-hd-assets.md` |
| Convert existing art into crisp pixel art | `pixelate-run` | `pixel-and-hd-assets.md` |
| Generate a UI sheet, HUD, menu, buttons, icons, or extract UI components | `ui-gen-run` | `ui-and-image-editing.md` |
| Edit one or more still images | `image-edit-run` | `ui-and-image-editing.md` |
| Quickly upgrade one asset or create several similarly sized, style-consistent variants | `one-click-upgrade-prompts`, then `one-click-upgrade-run` | `ui-and-image-editing.md` |
| Edit an animated GIF or WebP while preserving timing and layout | `animation-edit-run` | `ui-and-image-editing.md` |
| Find or download a standard 64×64 flat material texture | `texture-reference-search`, `texture-reference-download` | `maps-tiles-and-textures.md` |
| Create a seamless flat texture | `texture-gen-run` | `maps-tiles-and-textures.md` |
| Create an isometric texture | `isometric-texture-run` | `maps-tiles-and-textures.md` |
| Create a terrain tileset | `tileset-gen-run` | `maps-tiles-and-textures.md` |
| Create an isometric terrain tileset | `isometric-tileset-run` | `maps-tiles-and-textures.md` |
| Create square isometric or hex-isometric map tiles | `isometric-gen-run`, `hex-isometric-gen-run`, or HD variants | `maps-tiles-and-textures.md` |
| Create parallax-ready foreground, midground, and background layers | `side-scrolling-map-run` or `hd-side-scrolling-map-run` | `maps-tiles-and-textures.md` |
| Make an image loop horizontally, vertically, or as a texture | `self-loop-run` | `animation-and-video.md` |
| Create a short sprite animation | `animate-run` | `animation-and-video.md` |
| Control a complex frame animation with intermediate poses | `keyframes-run` | `animation-and-video.md` |
| Turn a first frame, or first and last frames, into a short clip | `video-run` | `animation-and-video.md` |
| Create one sound, a sound pack, or variants | `sound-run` | `audio.md` |
| Draft music direction or render a track | `music-run` | `audio.md` |

## Selection rules

- Use preset discovery before guessing a pixel, large-pixel, or HD preset: run `pixel-gen-template-info`, `large-pixel-template-info`, or `hd-gen-template-info`.
- Use preset-driven `pixel-gen-run` when exact dimensions or maximum pixel quality matter. Use `pixel-universal-gen-run` when low-cost volume and rapid prototyping matter more; it can produce many sprites on one general pixel canvas, but its per-sprite quality and size control are weaker.
- Use `pixel-universal-gen-run` for a flexible pixel scene or illustration rather than an exact small-sprite contract. Select `top-down` only when the camera must be overhead.
- Use `nano-banana-run` or `image-2-run` for unrestricted HD generation and batches. Use `ui-gen-run` instead when the requested sheet also needs automatic background removal and component segmentation; UI generation is prompt-driven and can produce ordinary assets or sprite sheets, not only interface graphics.
- Use `pixelate-run` only for explicit visual conversion; it is not a generic exact-size sprite generator.
- Use map reference search when the selected generator accepts a reference or preset. For side-scrolling maps, treat search results as visual planning material only; those commands do not accept a preset input.
- Treat preset output size and default count as part of the deliverable contract. If no preset matches the requested size or count, explain the gap instead of implying that prompt text can enforce it.
- Use pixel commands whenever the requested final asset is pixel art; do not route pixel work through a general illustration path.
- Use `image-edit-run` for one precise still-image transformation. Use one-click upgrade when one source should become a coherent upgrade sequence or several style-consistent variants. Use `animation-edit-run` for an existing animated GIF or WebP.
- Use `animate-run` for most animation because it directly produces WebP, GIF, or sprite-sheet frames. For an ordinary complex action, use `keyframes-run` to constrain intermediate poses while keeping frame-animation output. Its general frame mode still outputs at no more than 480p, regardless of a higher-resolution source. Use `video-run` only when frame animation remains insufficient or higher-resolution video is required.
- Use `texture-reference-search` and `texture-reference-download` first when a standard 64×64 flat material already fits. Use `texture-gen-run` to create and download a new 64×64 seamless texture, and `isometric-texture-run` when the final tile must already have a 2:1 isometric projection.
- Use `tileset-gen-run` for a 64px top-down dual-grid atlas. Select `foreground` or `background` with one matching 64×64 texture, or `dual` with both textures. Single-terrain modes can remove the unused background; dual mode cannot. Use `isometric-tileset-run` for an isometric atlas.

If no specialized capability fits, explain the gap instead of exposing an internal workflow or raw request surface.
