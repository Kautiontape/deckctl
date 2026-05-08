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


# Default icon size as a fraction of the key's available area (i.e. key
# height minus label strip if present). Picked low enough that icons
# from different families (Papirus app icons with tight viewboxes,
# FontAwesome with generous padding, etc.) read as visually similar in
# size, with a clear margin around the glyph.
DEFAULT_ICON_SCALE_WITH_LABEL = 0.55
DEFAULT_ICON_SCALE_NO_LABEL = 0.70

LABEL_STRIP_HEIGHT = 14


def render_key(
    *,
    size: tuple[int, int],
    icons: IconResolver,
    icon: str | None = None,
    label: str | None = None,
    font_family: str = "DejaVu Sans",
    bg: tuple[int, int, int] = (0, 0, 0),
    fg: tuple[int, int, int] = (255, 255, 255),
    icon_scale: float | None = None,
) -> Image.Image:
    """Compose a key. Icon is centered above the label (if any).

    `icon_scale` is a multiplier on the available square area — `0.55`
    means the icon takes 55% of the smaller of (key width, available
    height). Per-key override lets specific icons that read small at the
    default scale (e.g. wide icons that get squished) bump up.
    """
    w, h = size
    canvas = Image.new("RGB", size, bg)

    if icon:
        label_strip = LABEL_STRIP_HEIGHT if label else 0
        available_h = h - label_strip
        scale = icon_scale if icon_scale is not None else (
            DEFAULT_ICON_SCALE_WITH_LABEL if label else DEFAULT_ICON_SCALE_NO_LABEL
        )
        icon_size = max(8, int(min(w, available_h) * scale))
        img = icons.load(icon, size=icon_size)
        if img is not None:
            x = (w - img.width) // 2
            # Center the icon within the area ABOVE the label strip, not
            # within the whole key — gives consistent visible breathing
            # room between icon bottom and label top.
            y = (available_h - img.height) // 2
            canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)

    if label:
        draw = ImageDraw.Draw(canvas)
        font = _font(font_family, 11)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        x = (w - tw) // 2
        y = h - LABEL_STRIP_HEIGHT
        draw.text((x, y), label, font=font, fill=fg)

    return canvas
