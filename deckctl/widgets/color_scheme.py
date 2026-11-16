"""`color_scheme` widget — reflects the desktop dark-mode preference.

State comes from the XDG settings portal (see ColorSchemeService), so the
key follows changes made anywhere. Pressing runs `on_press`; point it at
whatever flips the preference (the dotfiles' `dark-mode` script).

Settings:
    on_press       command to run on tap (default: "dark-mode")
    on_long_press  command to run on hold (default: same as on_press)
    icon_on        icon when dark mode is on (default: moon)
    icon_off       icon when dark mode is off (default: sun)
    label          static label shown in both states (default: "Dark")
    label_on       overrides label when on
    label_off      overrides label when off
    icon_scale     forwarded to render_key
"""

from __future__ import annotations

import logging
import threading

from PIL.Image import Image

from ..actions import execute
from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("color_scheme")
class ColorSchemeWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None

        self.on_press_action: str = settings.get("on_press") or "dark-mode"
        self.on_long_press_action: str | None = settings.get("on_long_press")
        self.icon_on: str = settings.get("icon_on") or "moon"
        self.icon_off: str = settings.get("icon_off") or "sun"
        label = settings.get("label", "Dark")
        self.label_on: str | None = settings.get("label_on") or label
        self.label_off: str | None = settings.get("label_off") or label
        self.icon_scale = settings.get("icon_scale")

        self._state_lock = threading.Lock()
        self._is_on = False

        svc = deps.color_scheme  # type: ignore[attr-defined]
        if svc is not None:
            self._is_on = svc.is_dark()
            self._unsub = svc.subscribe(self._on_state_change)

    def _on_state_change(self) -> None:
        svc = self._deps.color_scheme  # type: ignore[attr-defined]
        if svc is None:
            return
        is_on = svc.is_dark()
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
            bg=(30, 35, 70) if is_on else (0, 0, 0),
            fg=(190, 200, 255) if is_on else (255, 255, 255),
            icon_scale=self.icon_scale,
        )

    def on_press(self, ctx) -> None:
        execute(self.on_press_action, ctx)

    def on_long_press(self, ctx) -> None:
        execute(self.on_long_press_action or self.on_press_action, ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
