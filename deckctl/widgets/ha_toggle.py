"""`ha_toggle` widget — reflects an HA entity's state and toggles it on press.

Settings:
    entity         "domain.entity_id" (required)
    service        "domain.service" (default: "<entity-domain>.toggle")
    target         entity_id passed to the service (default: same as `entity`)
    attribute      if set, read this attribute instead of top-level state
                   (e.g. "is_volume_muted" on a media_player)
    on_states      list of state strings considered "on" (default: ["on"])
    icon           single icon for both states (used when icon_on/_off omitted)
    icon_on        icon when state is on
    icon_off       icon when state is off
    label          static label (or label_on / label_off for state-specific)
    label_on       label when on
    label_off      label when off
    icon_scale     forwarded to render_key
"""

from __future__ import annotations

import logging
import threading

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("ha_toggle")
class HAToggleWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None

        self.entity: str = settings.get("entity", "")
        self.target: str = settings.get("target") or self.entity
        self.attribute: str | None = settings.get("attribute")
        self.on_states: list[str] = list(settings.get("on_states", ["on"]))

        # Service: explicit "domain.service", else derive "<entity-domain>.toggle".
        explicit = settings.get("service")
        if explicit and "." in explicit:
            self.domain, _, self.service = explicit.partition(".")
        else:
            domain = self.entity.split(".", 1)[0] if "." in self.entity else ""
            self.domain = domain
            self.service = "toggle"

        # Icons + labels — fall back to the shared `icon`/`label` for both states.
        icon = settings.get("icon")
        self.icon_on: str | None = settings.get("icon_on") or icon
        self.icon_off: str | None = settings.get("icon_off") or icon
        label = settings.get("label")
        self.label_on: str | None = settings.get("label_on") or label
        self.label_off: str | None = settings.get("label_off") or label
        self.icon_scale = settings.get("icon_scale")

        self._state_lock = threading.Lock()
        self._is_on = False

        ha = deps.ha  # type: ignore[attr-defined]
        if ha is not None and self.entity:
            # Pull initial state on a worker so the first render is right.
            threading.Thread(target=self._prime, daemon=True).start()
            self._unsub = ha.subscribe_state(self.entity, self._on_state_change)

    # ─── state ────────────────────────────────────────────────────────────

    def _compute_is_on(self, state_dict: dict) -> bool:
        if self.attribute:
            v = (state_dict.get("attributes") or {}).get(self.attribute)
            return bool(v)
        return state_dict.get("state") in self.on_states

    def _on_state_change(self, state_dict: dict) -> None:
        is_on = self._compute_is_on(state_dict)
        with self._state_lock:
            changed = is_on != self._is_on
            self._is_on = is_on
        if changed:
            cb = self.invalidate
            if cb is not None:
                cb()

    def _prime(self) -> None:
        ha = self._deps.ha  # type: ignore[attr-defined]
        if ha is None:
            return
        s = ha.state(self.entity)
        if s is not None:
            self._on_state_change(s)

    # ─── render + actions ─────────────────────────────────────────────────

    def render(self) -> Image:
        with self._state_lock:
            is_on = self._is_on
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon_on if is_on else self.icon_off,
            label=self.label_on if is_on else self.label_off,
            font_family=self._deps.font,
            bg=(40, 60, 30) if is_on else (0, 0, 0),
            fg=(220, 240, 200) if is_on else (255, 255, 255),
            icon_scale=self.icon_scale,
        )

    def on_press(self, ctx) -> None:
        ha = self._deps.ha  # type: ignore[attr-defined]
        if ha is None or not self.domain or not self.service:
            return
        ha.call_service(self.domain, self.service, entity_id=self.target)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
