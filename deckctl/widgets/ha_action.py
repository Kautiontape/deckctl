"""`ha_action` widget — fires a Home Assistant service call on press.

Settings:
    service     "domain.service"   e.g. "script.toggle_mute_office_speaker"
                                   or "media_player.volume_up"
    target      entity_id          optional; passed as entity_id in the call
    icon        icon name          rendered like a command widget
    label       label              rendered like a command widget
    data        TOML inline table  optional extra payload
"""

from __future__ import annotations

import logging

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("ha_action")
class HAActionWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.icon: str | None = settings.get("icon")
        self.label: str | None = settings.get("label")
        self.target: str | None = settings.get("target")
        self.data: dict = dict(settings.get("data") or {})

        service = settings.get("service", "")
        if "." not in service:
            log.warning("ha_action: bad service %r (expected domain.service)", service)
            self.domain, self.service = "", ""
        else:
            self.domain, _, self.service = service.partition(".")

    def render(self) -> Image:
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=self.label,
            font_family=self._deps.font,
        )

    def on_press(self, ctx) -> None:
        ha = self._deps.ha  # type: ignore[attr-defined]
        if ha is None:
            log.warning("ha_action: HA service not initialized")
            return
        if not self.domain or not self.service:
            return
        ha.call_service(
            self.domain, self.service,
            entity_id=self.target,
            data=self.data,
        )

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)
