"""`sway_window` widget — one window button. Built dynamically by RecentsProducer.

Settings (supplied by the producer):
    con_id      sway container id (int)
    app_id      sway app_id or window_properties.class
    name        window title
"""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from .sway_mark import _normalize_app_id
from . import WidgetDeps, register


@register("sway_window")
class SwayWindowWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.con_id = int(settings.get("con_id", 0))
        self.app_id: str = settings.get("app_id", "") or ""
        self.name: str = settings.get("name", "") or ""

    def render(self) -> Image:
        icon = _normalize_app_id(self.app_id) or ""
        if not icon or self._deps.icons.resolve(icon) is None:  # type: ignore[attr-defined]
            icon = "window-restore"
        label = self.name or self.app_id or "?"
        if len(label) > 11:
            label = label[:10] + "…"
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=icon,
            label=label,
            font_family=self._deps.font,
        )

    def on_press(self, ctx) -> None:
        sway = self._deps.sway  # type: ignore[attr-defined]
        if sway is None or not self.con_id:
            return
        sway.focus_con(self.con_id)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)
