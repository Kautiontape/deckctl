"""`dynamic_page` widget — paginates a named dynamic region.

Settings:
    target       region name (matches `name` on a `[[keys]] type="dynamic"`)
    direction    "next" (default) or "prev"
    icon         icon override (defaults: go-next / go-previous)

When the target region has only one page, the widget renders blank so
it doesn't clutter the deck with inert controls.
"""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register


@register("dynamic_page")
class DynamicPageWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.target: str = settings.get("target", "")
        self.direction: str = settings.get("direction", "next")
        if self.direction not in {"next", "prev"}:
            self.direction = "next"
        default_icon = "go-next" if self.direction == "next" else "go-previous"
        self.icon: str = settings.get("icon") or default_icon

        self._region = None
        self._unsub = None
        active = getattr(deps, "active_page", None)
        if active is not None and self.target:
            self._region = active.get_region(self.target)
            if self._region is not None:
                self._unsub = self._region.subscribe(self._on_region_change)

    def _on_region_change(self) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()

    def render(self) -> Image:
        region = self._region
        if region is None or region.total_pages <= 1:
            return render_key(
                size=self._deps.key_size,
                icons=self._deps.icons,  # type: ignore[arg-type]
                icon=None,
                label=None,
                font_family=self._deps.font,
            )
        if self.direction == "next":
            enabled = region.page_num < region.total_pages - 1
        else:
            enabled = region.page_num > 0
        label = f"{region.page_num + 1}/{region.total_pages}"
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=label,
            font_family=self._deps.font,
            fg=(255, 255, 255) if enabled else (90, 90, 90),
        )

    def on_press(self, ctx) -> None:
        region = self._region
        if region is None:
            return
        if self.direction == "next":
            region.go_to_page(region.page_num + 1)
        else:
            region.go_to_page(region.page_num - 1)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
