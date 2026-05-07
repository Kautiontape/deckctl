"""Compose a single key image from icon + label."""

from __future__ import annotations

import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .icons import IconResolver


def overlay_progress_arc(
    base: "Image.Image",
    progress: float,
    *,
    color: tuple[int, int, int, int] = (255, 200, 60, 240),
    width: int = 5,
    inset: int = 4,
) -> "Image.Image":
    """Return a copy of `base` with a clockwise progress arc on top.

    `progress` is clamped to [0, 1]. The arc starts at 12 o'clock and
    grows clockwise. Used by the power page to give visible feedback while
    a destructive long-press is being held.
    """
    progress = max(0.0, min(1.0, progress))
    out = base.copy().convert("RGB")
    if progress <= 0:
        return out
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    bbox = (inset, inset, out.size[0] - inset, out.size[1] - inset)
    sweep = progress * 360
    # Pillow's arc: start/end angles in degrees, 0 is east. Shift so 0 is
    # north (top) and we grow clockwise.
    od.arc(bbox, start=-90, end=-90 + sweep, fill=color, width=width)
    return Image.alpha_composite(out.convert("RGBA"), overlay).convert("RGB")


@lru_cache(maxsize=8)
def _font_path(family: str) -> str | None:
    """Resolve a font family to a file path via fc-match. None if unavailable."""
    try:
        out = subprocess.check_output(
            ["fc-match", "-f", "%{file}", family],
            text=True,
            timeout=2,
        ).strip()
        return out or None
    except Exception:
        return None


def _font(family: str, size: int):
    path = _font_path(family) or _font_path("sans")
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_key(
    *,
    size: tuple[int, int],
    icons: IconResolver,
    icon: str | None = None,
    label: str | None = None,
    font_family: str = "DejaVu Sans",
    bg: tuple[int, int, int] = (0, 0, 0),
    fg: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Compose a key. Icon is centered, label sits at the bottom."""
    w, h = size
    canvas = Image.new("RGB", size, bg)

    if icon:
        # Reserve bottom strip for label if present.
        icon_box = (h - 14) if label else int(h * 0.85)
        img = icons.load(icon, size=icon_box)
        if img is not None:
            x = (w - img.width) // 2
            y = (icon_box - img.height) // 2
            canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)

    if label:
        draw = ImageDraw.Draw(canvas)
        font = _font(font_family, 11)
        # Right-anchor measured width to compute centering.
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = h - 14
        draw.text((x, y), label, font=font, fill=fg)

    return canvas
