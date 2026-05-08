"""`idle_inhibit` widget — manual sleep/idle hold via systemd-inhibit.

Settings:
    icon_on        icon when inhibitor is held (default: mug-hot)
    icon_off       icon when inhibitor is released (default: moon)
    label          static label (default: "Awake")
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


@register("idle_inhibit")
class IdleInhibitWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None

        self.icon_on: str = settings.get("icon_on") or "mug-hot"
        self.icon_off: str = settings.get("icon_off") or "moon"
        label = settings.get("label", "Awake")
        self.label_on: str | None = settings.get("label_on") or label
        self.label_off: str | None = settings.get("label_off") or label
        self.icon_scale = settings.get("icon_scale")

        self._state_lock = threading.Lock()
        self._is_on = False

        svc = deps.inhibit  # type: ignore[attr-defined]
        if svc is not None:
            self._is_on = svc.is_inhibited()
            self._unsub = svc.subscribe(self._on_state_change)

    def _on_state_change(self) -> None:
        svc = self._deps.inhibit  # type: ignore[attr-defined]
        if svc is None:
            return
        is_on = svc.is_inhibited()
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
            bg=(60, 50, 20) if is_on else (0, 0, 0),
            fg=(245, 220, 160) if is_on else (255, 255, 255),
            icon_scale=self.icon_scale,
        )

    def on_press(self, ctx) -> None:
        svc = self._deps.inhibit  # type: ignore[attr-defined]
        if svc is None:
            return
        svc.toggle()

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
