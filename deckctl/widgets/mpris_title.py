"""`mpris_title` widget — reactive track title (with artist) text key."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..render import _font
from . import WidgetDeps, register


def _wrap(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Greedy word-wrap to a maximum pixel width. Up to 3 lines."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) >= 3:
            break
    if current and len(lines) < 3:
        lines.append(current)
    return lines[:3]


@register("mpris_title")
class MprisTitleWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self.player: str = settings.get("player", "Feishin")
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        if deps.mpris is not None:
            self._unsub = deps.mpris.subscribe(self.player, self._on_change)

    def render(self) -> Image.Image:
        title, artist = "", ""
        if self._deps.mpris is not None:
            s = self._deps.mpris.state(self.player)
            if s is not None:
                title = s.get("title", "")
                artist = s.get("artist", "")

        w, h = self._deps.key_size
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        d = ImageDraw.Draw(canvas)

        if not title:
            font = _font(self._deps.font, 11)
            label = "(no track)"
            bbox = d.textbbox((0, 0), label, font=font)
            d.text(
                ((w - (bbox[2] - bbox[0])) // 2, (h - 14) // 2),
                label, font=font, fill=(120, 120, 120),
            )
            return canvas

        # Title takes up the top portion; artist sits underneath.
        title_font = _font(self._deps.font, 10)
        artist_font = _font(self._deps.font, 9)
        margin = 4

        title_lines = _wrap(title, title_font, w - 2 * margin, d)
        # If title fits in 1-2 lines, leave room for artist; otherwise use 3.
        max_artist = 1 if len(title_lines) <= 2 else 0
        artist_lines = _wrap(artist, artist_font, w - 2 * margin, d)[:max_artist]

        # Layout vertically centered.
        line_h = 12
        total = len(title_lines) * line_h + len(artist_lines) * 11
        y = (h - total) // 2
        for line in title_lines:
            bbox = d.textbbox((0, 0), line, font=title_font)
            d.text(((w - (bbox[2] - bbox[0])) // 2, y), line, font=title_font, fill=(255, 255, 255))
            y += line_h
        for line in artist_lines:
            bbox = d.textbbox((0, 0), line, font=artist_font)
            d.text(((w - (bbox[2] - bbox[0])) // 2, y), line, font=artist_font, fill=(180, 180, 180))
            y += 11
        return canvas

    def on_press(self, ctx) -> None:
        # Tap title = play/pause (cheap convenience).
        if self._deps.mpris is not None:
            self._deps.mpris.play_pause(self.player)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def _on_change(self) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
