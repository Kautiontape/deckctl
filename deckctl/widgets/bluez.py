"""Bluetooth widgets.

`bluez` — one Bluetooth device (paired or scan-discovered). Built
dynamically by BluezProducer.

`bluez_scan` — static button that toggles BlueZ discovery.
"""

from __future__ import annotations

import threading

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
        self.paired: bool = bool(settings.get("paired", True))

    def render(self) -> Image.Image:
        if not self.paired:
            bg = (40, 40, 40)
        elif self.connected:
            bg = (20, 50, 60)
        else:
            bg = (0, 0, 0)
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=_short_label(self.name),
            font_family=self._deps.font,
            bg=bg,
        )
        d = ImageDraw.Draw(img, "RGBA")
        w, _ = img.size
        if self.connected:
            d.rectangle(((0, 0), (w, 3)), fill=(80, 180, 255, 255))
        elif not self.paired:
            # Amber stripe to flag "discovered, tap to pair".
            d.rectangle(((0, 0), (w, 3)), fill=(220, 160, 40, 255))
        return img

    def on_press(self, ctx) -> None:
        bluez = getattr(self._deps, "bluez", None)
        if bluez is None or not self.path:
            return
        if not self.paired:
            bluez.pair(self.path)
            return
        bluez.toggle(self.path, self.connected)

    def on_long_press(self, ctx) -> None:
        bluez = getattr(self._deps, "bluez", None)
        if bluez is None or not self.path:
            return
        # Forget the device. For unpaired discovered devices a long-press
        # is meaningless; fall back to the tap action (pair).
        if self.paired:
            bluez.remove_device(self.path)
        else:
            bluez.pair(self.path)


@register("bluez_scan")
class BluezScanWidget:
    """Toggles BlueZ discovery on the default adapter. Highlights itself
    while a scan is in progress so the UI state matches BlueZ state even
    if scanning was started elsewhere."""

    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None
        self.icon: str = settings.get("icon") or "blueman-scanner"
        self.label: str = settings.get("label", "Scan")
        self.label_scanning: str = settings.get("label_scanning", "Scanning…")

        self._state_lock = threading.Lock()
        self._scanning = False
        self._unsub = None

        bz = deps.bluez  # type: ignore[attr-defined]
        if bz is not None:
            self._scanning = bz.discovering
            self._unsub = bz.subscribe(self._on_state_change)

    def _on_state_change(self) -> None:
        bz = self._deps.bluez  # type: ignore[attr-defined]
        if bz is None:
            return
        scanning = bz.discovering
        with self._state_lock:
            changed = scanning != self._scanning
            self._scanning = scanning
        if changed:
            cb = self.invalidate
            if cb is not None:
                cb()

    def render(self) -> Image.Image:
        with self._state_lock:
            scanning = self._scanning
        img = render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=self.icon,
            label=self.label_scanning if scanning else self.label,
            font_family=self._deps.font,
            bg=(20, 50, 60) if scanning else (0, 0, 0),
        )
        if scanning:
            d = ImageDraw.Draw(img, "RGBA")
            w, _ = img.size
            d.rectangle(((0, 0), (w, 3)), fill=(80, 180, 255, 255))
        return img

    def on_press(self, ctx) -> None:
        bz = self._deps.bluez  # type: ignore[attr-defined]
        if bz is None:
            return
        if bz.discovering:
            bz.stop_discovery()
        else:
            bz.start_discovery()

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
