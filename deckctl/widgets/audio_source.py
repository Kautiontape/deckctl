"""`audio_source` widget — one PipeWire input source. Built dynamically by AudioSourceProducer."""

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


def _icon_for(source_name: str) -> str:
    name = source_name.lower()
    if "bluez" in name:
        return "bluetooth"
    if "webcam" in name or "camera" in name:
        return "camera-web"
    if "usb" in name or "yeti" in name or "blue_micro" in name:
        return "microphone"
    return "audio-input-microphone"


@register("audio_source")
class AudioSourceWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.source_name: str = settings.get("source_name", "")
        self.description: str = settings.get("description") or self.source_name
        self.is_default: bool = bool(settings.get("is_default"))

    def render(self) -> Image.Image:
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=_icon_for(self.source_name),
            label=_short_label(self.description),
            font_family=self._deps.font,
            bg=(20, 50, 30) if self.is_default else (0, 0, 0),
        )
        if self.is_default:
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((0, 0), (w, 3)), fill=(80, 220, 120, 255))
        return img

    def on_press(self, ctx) -> None:
        pw = self._deps.pipewire  # type: ignore[attr-defined]
        if pw is None or not self.source_name:
            return
        pw.set_default_source(self.source_name)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)
