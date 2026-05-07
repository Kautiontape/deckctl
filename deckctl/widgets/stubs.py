"""Stub widgets for types not yet implemented.

Each renders an icon + label like a `command` widget, but ignores presses
(logs a warning instead). They exist so the configured layout can be drawn
on the deck before later build steps replace them with the real widgets.

Remove a registration here when the real widget for that type is added.
"""

from __future__ import annotations

import logging

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


class _Stub:
    type_name = "stub"

    def __init__(self, settings: dict, deps: WidgetDeps):
        self.settings = settings
        self._deps = deps
        self.invalidate = None

    def render(self) -> Image:
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.settings.get("icon"),
            label=self.settings.get("label") or self.type_name,
            font_family=self._deps.font,
            # Dim the canvas a touch so stubs are visually distinguishable.
            bg=(20, 20, 20),
            fg=(180, 180, 180),
        )

    def on_press(self, ctx) -> None:
        log.warning("widget %r not yet implemented; press ignored", self.type_name)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)


def _stub_for(type_name: str) -> type:
    cls = type(
        f"Stub_{type_name}",
        (_Stub,),
        {"type_name": type_name},
    )
    return register(type_name)(cls)


for _t in ("clock",):
    _stub_for(_t)
