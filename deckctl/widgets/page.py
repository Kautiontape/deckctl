"""`page` widget — same render shape as `command`, but its press pushes a page."""

from __future__ import annotations

from PIL.Image import Image

from ..actions import execute
from ..render import render_key
from . import WidgetDeps, register


@register("page")
class PageWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self.icon: str | None = settings.get("icon")
        self.label: str | None = settings.get("label")
        self.target: str = settings["target"]
        self.on_long_press_action: str | None = settings.get("on_long_press")
        self.icon_scale = settings.get("icon_scale")
        self._deps = deps
        self.invalidate = None

    def render(self) -> Image:
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=self.label,
            font_family=self._deps.font,
            icon_scale=self.icon_scale,
        )

    def on_press(self, ctx) -> None:
        execute(f"page:{self.target}", ctx)

    def on_long_press(self, ctx) -> None:
        if self.on_long_press_action:
            execute(self.on_long_press_action, ctx)
            return
        self.on_press(ctx)
