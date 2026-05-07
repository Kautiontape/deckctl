"""`mpris_shuffle` widget — reactive shuffle on/off indicator."""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register


@register("mpris_shuffle")
class MprisShuffleWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self.player: str = settings.get("player", "Feishin")
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        if deps.mpris is not None:
            self._unsub = deps.mpris.subscribe(self.player, self._on_change)

    def render(self) -> Image:
        shuffle = False
        if self._deps.mpris is not None:
            state = self._deps.mpris.state(self.player)
            if state is not None:
                shuffle = bool(state.get("shuffle", False))

        bg = (20, 40, 70) if shuffle else (20, 20, 20)
        fg = (255, 255, 255) if shuffle else (140, 140, 140)
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon="shuffle",
            label="Shuffle",
            font_family=self._deps.font,
            bg=bg, fg=fg,
        )

    def on_press(self, ctx) -> None:
        if self._deps.mpris is None:
            return
        state = self._deps.mpris.state(self.player)
        cur = bool(state.get("shuffle", False)) if state else False
        self._deps.mpris.set_shuffle(self.player, not cur)

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
