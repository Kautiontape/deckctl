"""`sway_mark_new` widget — toggles assign mode on the marks page."""

from __future__ import annotations

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register


@register("sway_mark_new")
class SwayMarkNewWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        marks = deps.marks  # type: ignore[attr-defined]
        if marks is not None:
            self._unsub = marks.subscribe(self._on_change)

    def render(self) -> Image:
        marks = self._deps.marks  # type: ignore[attr-defined]
        assign = marks.assign_mode if marks else False
        if assign:
            return render_key(
                size=self._deps.key_size,
                icons=self._deps.icons,  # type: ignore[arg-type]
                icon="xmark",
                label="Cancel",
                font_family=self._deps.font,
                bg=(60, 30, 30),
            )
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon="plus",
            label="New Mark",
            font_family=self._deps.font,
        )

    def on_press(self, ctx) -> None:
        marks = self._deps.marks  # type: ignore[attr-defined]
        if marks is None:
            return
        marks.set_assign_mode(not marks.assign_mode)

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
