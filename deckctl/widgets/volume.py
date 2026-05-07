"""`volume` widget — adjust default audio sink."""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register


@register("volume")
class VolumeWidget:
    """Settings:

        direction   "up" | "down" | "mute"
        step        percentage step for up/down (default 5)
    """

    def __init__(self, settings: dict, deps: WidgetDeps):
        self.direction: str = settings.get("direction", "up")
        self.step: int = int(settings.get("step", 5))
        self._deps = deps
        self.invalidate = None

        if deps.pipewire is not None:  # type: ignore[attr-defined]
            deps.pipewire.subscribe(self._on_change)  # type: ignore[attr-defined]

    def render(self) -> Image:
        vol, muted = (0.0, False)
        if self._deps.pipewire is not None:  # type: ignore[attr-defined]
            vol, muted = self._deps.pipewire.state()  # type: ignore[attr-defined]

        if self.direction == "mute":
            icon = "audio-volume-muted" if muted else self._level_icon(vol)
            label = "Mute" if not muted else "Unmute"
        elif self.direction == "down":
            icon = "audio-volume-low"
            label = f"-{self.step}% · {int(vol * 100)}%"
        else:  # up
            icon = "audio-volume-high"
            label = f"+{self.step}% · {int(vol * 100)}%"

        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=icon,
            label=label,
            font_family=self._deps.font,
        )

    @staticmethod
    def _level_icon(vol: float) -> str:
        if vol < 0.01:
            return "audio-volume-muted"
        if vol < 0.34:
            return "audio-volume-low"
        if vol < 0.67:
            return "audio-volume-medium"
        return "audio-volume-high"

    def on_press(self, ctx) -> None:
        pw = self._deps.pipewire  # type: ignore[attr-defined]
        if pw is None:
            return
        if self.direction == "mute":
            pw.toggle_mute()
        elif self.direction == "down":
            pw.adjust(-self.step)
        else:
            pw.adjust(+self.step)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def _on_change(self) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()
