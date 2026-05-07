"""`sway_mark` widget — one slot on the marks page.

Settings:
    slot   integer 1..12

Render:
    empty + normal     → dim background, "Slot N" label
    empty + assign     → bright border, "Slot N" label, "Assign?" hint
    filled + normal    → app icon + truncated window name
    filled + assign    → app icon, "Replace?" hint
"""

from __future__ import annotations

import logging
import re

from PIL import Image, ImageDraw

from ..render import _font, render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


def _normalize_app_id(app_id: str) -> str:
    """Map sway app_id → likely Papirus icon-theme name.

    org.keepassxc.KeePassXC → keepassxc
    vivaldi-stable          → vivaldi
    foot                    → foot
    """
    if not app_id:
        return ""
    if "." in app_id:
        app_id = app_id.rsplit(".", 1)[-1]
    s = app_id.lower()
    s = re.sub(r"-(stable|beta|canary|nightly|dev)$", "", s)
    return s


@register("sway_mark")
class SwayMarkWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        try:
            self.slot = int(settings["slot"])
        except (KeyError, ValueError):
            log.warning("sway_mark: bad slot %r", settings.get("slot"))
            self.slot = 0

        marks = deps.marks  # type: ignore[attr-defined]
        if marks is not None:
            self._unsub = marks.subscribe(self._on_change)

    def render(self) -> Image.Image:
        marks = self._deps.marks  # type: ignore[attr-defined]
        info = marks.slot(self.slot) if marks else None
        assign = marks.assign_mode if marks else False

        if info is None:
            # Empty slot.
            label = f"Slot {self.slot}"
            bg = (40, 40, 70) if assign else (20, 20, 20)
            fg = (200, 200, 240) if assign else (140, 140, 140)
            img = render_key(
                size=self._deps.key_size,
                icons=self._deps.icons,  # type: ignore[arg-type]
                icon=None,
                label=label,
                font_family=self._deps.font,
                bg=bg, fg=fg,
            )
            if assign:
                self._draw_hint(img, "tap")
            return img

        # Filled slot.
        icon_name = _normalize_app_id(info.get("app_id", ""))
        name = info.get("name") or info.get("app_id") or "?"
        if len(name) > 12:
            name = name[:11] + "…"

        # Try app icon, then a generic window glyph.
        if self._deps.icons.resolve(icon_name) is None:  # type: ignore[attr-defined]
            icon_name = "window-restore"

        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=icon_name,
            label=name,
            font_family=self._deps.font,
        )
        if assign:
            self._draw_hint(img, "replace")
        return img

    def _draw_hint(self, img: Image.Image, kind: str) -> None:
        w, h = img.size
        d = ImageDraw.Draw(img, "RGBA")
        # Bright top border to signal assign mode.
        d.rectangle(((0, 0), (w, 3)), fill=(255, 200, 50, 255))
        if kind == "replace":
            # Tag the corner so user knows tapping replaces.
            font = _font(self._deps.font, 9)
            d.rectangle(((w - 38, 4), (w - 2, 16)), fill=(0, 0, 0, 200))
            d.text((w - 35, 5), "replace", font=font, fill=(255, 200, 50))

    def on_press(self, ctx) -> None:
        marks = self._deps.marks  # type: ignore[attr-defined]
        if marks is None:
            return
        if marks.assign_mode:
            ok = marks.assign_focused(self.slot)
            if ok:
                marks.set_assign_mode(False)
        else:
            marks.activate(self.slot)

    def on_long_press(self, ctx) -> None:
        # Long-press on an occupied slot in normal mode clears it.
        # Easy escape hatch without an explicit "delete mode".
        marks = self._deps.marks  # type: ignore[attr-defined]
        if marks is None:
            return
        if not marks.assign_mode and marks.slot(self.slot) is not None:
            marks.clear(self.slot)
        else:
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
