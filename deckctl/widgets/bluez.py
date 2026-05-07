"""`bluez` widget — one paired Bluetooth device. Built dynamically by BluezProducer."""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..render import render_key
from . import WidgetDeps, register


def _short_label(s: str, limit: int = 11) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    first = s.split()[0]
    if len(first) <= limit:
        return first
    return s[: limit - 1] + "…"


@register("bluez")
class BluezWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.path: str = settings.get("path", "")
        self.name: str = settings.get("name") or self.path
        self.icon: str = settings.get("icon") or "bluetooth"
        self.connected: bool = bool(settings.get("connected"))

    def render(self) -> Image.Image:
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=_short_label(self.name),
            font_family=self._deps.font,
            bg=(20, 50, 60) if self.connected else (0, 0, 0),
        )
        if self.connected:
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((0, 0), (w, 3)), fill=(80, 180, 255, 255))
        return img

    def on_press(self, ctx) -> None:
        bluez = getattr(self._deps, "bluez", None)
        if bluez is None or not self.path:
            return
        bluez.toggle(self.path, self.connected)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)
