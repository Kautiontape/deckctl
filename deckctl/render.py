"""Compose a single key image from icon + label."""

from __future__ import annotations

import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .icons import IconResolver


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
