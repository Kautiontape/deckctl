"""`mic_mute` widget — toggle the default audio source mute."""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from ..services.pipewire import DEFAULT_SOURCE
from . import WidgetDeps, register


@register("mic_mute")
class MicMuteWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        if deps.pipewire is not None:  # type: ignore[attr-defined]
            deps.pipewire.subscribe(self._on_change)  # type: ignore[attr-defined]

    def render(self) -> Image:
        muted = False
        if self._deps.pipewire is not None:  # type: ignore[attr-defined]
            _, muted = self._deps.pipewire.state(DEFAULT_SOURCE)  # type: ignore[attr-defined]
        icon = "microphone-slash" if muted else "microphone"
        label = "Muted" if muted else "Mic On"
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=icon,
            label=label,
            font_family=self._deps.font,
        )

    def on_press(self, ctx) -> None:
        pw = self._deps.pipewire  # type: ignore[attr-defined]
        if pw is None:
            return
        pw.toggle_mute(DEFAULT_SOURCE)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def _on_change(self) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()
