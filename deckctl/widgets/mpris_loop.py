"""`mpris_loop` widget — reactive LoopStatus indicator."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..render import _font, render_key
from . import WidgetDeps, register


@register("mpris_loop")
class MprisLoopWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self.player: str = settings.get("player", "Feishin")
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        if deps.mpris is not None:
            self._unsub = deps.mpris.subscribe(self.player, self._on_change)

    def render(self) -> Image.Image:
        loop = "None"
        if self._deps.mpris is not None:
            state = self._deps.mpris.state(self.player)
            if state is not None:
                loop = state.get("loop_status", "None")

        if loop == "None":
            bg, fg = (20, 20, 20), (140, 140, 140)
            label = "Loop"
        elif loop == "Playlist":
            bg, fg = (20, 40, 70), (255, 255, 255)
            label = "List"
        else:  # Track
            bg, fg = (30, 60, 100), (255, 255, 255)
            label = "Track"

        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon="repeat",
            label=label,
            font_family=self._deps.font,
            bg=bg, fg=fg,
        )
        if loop == "Track":
            # Tiny "1" badge top-right for one-track loop.
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((w - 16, 0), (w, 16)), fill=(80, 180, 255, 220))
            d.text((w - 11, 1), "1", font=_font(self._deps.font, 11), fill=(0, 0, 0))
        return img

    def on_press(self, ctx) -> None:
        if self._deps.mpris is not None:
            self._deps.mpris.cycle_loop(self.player)

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
