"""`sway_workspace` widget — one workspace key with live current-WS highlighting.

Settings:
    workspace   integer 1..N
    label       optional override (default: "WS <n>")
    icon        optional icon
    action      one of "switch" (default) or "move":
                  switch → swaymsg workspace number <n>
                  move   → swaymsg move container to workspace <n>
                Override fully by setting `on_press` like a command widget.
    on_press    optional explicit action string
    on_long_press   optional
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..actions import execute
from ..render import render_key
from . import WidgetDeps, register


@register("sway_workspace")
class SwayWorkspaceWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        try:
            self.workspace = int(settings["workspace"])
        except (KeyError, ValueError):
            self.workspace = 0
        self.label = settings.get("label") or f"WS {self.workspace}"
        self.icon = settings.get("icon")
        action = settings.get("action", "switch")
        if "on_press" in settings:
            self._on_press_action = settings["on_press"]
        elif action == "move":
            self._on_press_action = (
                f"swaymsg move container to workspace {self.workspace}"
            )
        else:  # switch
            self._on_press_action = f"swaymsg workspace number {self.workspace}"
        self._on_long_press_action = settings.get("on_long_press")

        sway = getattr(deps, "_sway", None)
        # ActivePage doesn't currently put SwayService in deps; we look it
        # up via a known ad-hoc attribute. The daemon assigns deps.sway in
        # _build_active_page (see __main__.py).
        self.sway = sway or getattr(deps, "sway", None)
        if self.sway is not None:
            sub = getattr(self.sway, "subscribe_workspace_events", None)
            if sub is not None:
                self._unsub = sub(self._on_change)

    def _is_current(self) -> bool:
        if self.sway is None:
            return False
        cur = self.sway.current_workspace()
        return cur == self.workspace

    def render(self) -> Image.Image:
        active = self._is_current()
        bg = (20, 60, 90) if active else (0, 0, 0)
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=self.label,
            font_family=self._deps.font,
            bg=bg,
        )
        if active:
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((0, 0), (w, 3)), fill=(120, 200, 255, 255))
        return img

    def on_press(self, ctx) -> None:
        execute(self._on_press_action, ctx)

    def on_long_press(self, ctx) -> None:
        if self._on_long_press_action:
            execute(self._on_long_press_action, ctx)
            return
        self.on_press(ctx)

    def _on_change(self, _event=None) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
