"""`audio_sink` widget — one PipeWire sink. Built dynamically by AudioSinkProducer.

Settings (supplied by the producer, not the user):
    sink_name      stable PipeWire name, e.g. "bluez_output.…"
    description    human-friendly label
    is_default     bool — currently the system default sink
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..render import render_key
from . import WidgetDeps, register


def _short_label(s: str, limit: int = 11) -> str:
    """Trim long sink descriptions so they fit a key label."""
    s = s.strip()
    if len(s) <= limit:
        return s
    # Prefer first one or two words if a single word is short enough.
    first = s.split()[0]
    if len(first) <= limit:
        return first
    return s[: limit - 1] + "…"


def _icon_for(sink_name: str) -> str:
    name = sink_name.lower()
    if "bluez" in name:
        return "bluetooth"
    if "hdmi" in name:
        return "video-display"
    if "usb" in name:
        return "audio-headphones"
    return "audio-volume-high"


@register("audio_sink")
class AudioSinkWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.sink_name: str = settings.get("sink_name", "")
        self.description: str = settings.get("description") or self.sink_name
        self.is_default: bool = bool(settings.get("is_default"))

    def render(self) -> Image.Image:
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=_icon_for(self.sink_name),
            label=_short_label(self.description),
            font_family=self._deps.font,
            bg=(20, 50, 30) if self.is_default else (0, 0, 0),
        )
        if self.is_default:
            # Bright top border so the active sink is unmistakable.
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((0, 0), (w, 3)), fill=(80, 220, 120, 255))
        return img

    def on_press(self, ctx) -> None:
        pw = self._deps.pipewire  # type: ignore[attr-defined]
        if pw is None or not self.sink_name:
            return
        pw.set_default_sink(self.sink_name)

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)
