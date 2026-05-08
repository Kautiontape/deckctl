"""`swaync_dnd` widget — reflects DND state on swaync, taps to toggle.

Settings:
    icon_on        icon when DND is active (default: bell-slash)
    icon_off       icon when DND is inactive (default: bell)
    label          static label shown in both states (default: "DND")
    label_on       overrides label when on
    label_off      overrides label when off
    icon_scale     forwarded to render_key
"""

from __future__ import annotations

import logging
import threading

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("swaync_dnd")
class SwayncDndWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None

        self.icon_on: str = settings.get("icon_on") or "bell-slash"
        self.icon_off: str = settings.get("icon_off") or "bell"
        label = settings.get("label", "DND")
        self.label_on: str | None = settings.get("label_on") or label
        self.label_off: str | None = settings.get("label_off") or label
        self.icon_scale = settings.get("icon_scale")

        self._state_lock = threading.Lock()
        self._is_on = False

        sw = deps.swaync  # type: ignore[attr-defined]
        if sw is not None:
            self._is_on = sw.get_dnd()
            self._unsub = sw.subscribe(self._on_state_change)

    def _on_state_change(self) -> None:
        sw = self._deps.swaync  # type: ignore[attr-defined]
        if sw is None:
            return
        is_on = sw.get_dnd()
        with self._state_lock:
            changed = is_on != self._is_on
            self._is_on = is_on
        if changed:
            cb = self.invalidate
            if cb is not None:
                cb()

    def render(self) -> Image:
        with self._state_lock:
            is_on = self._is_on
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon_on if is_on else self.icon_off,
            label=self.label_on if is_on else self.label_off,
            font_family=self._deps.font,
            bg=(60, 30, 30) if is_on else (0, 0, 0),
            fg=(255, 200, 180) if is_on else (255, 255, 255),
            icon_scale=self.icon_scale,
        )

    def on_press(self, ctx) -> None:
        sw = self._deps.swaync  # type: ignore[attr-defined]
        if sw is None:
            return
        sw.toggle_dnd()

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
