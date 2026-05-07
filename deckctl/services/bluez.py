"""BlueZ D-Bus client.

BlueZ lives on the system bus (not session). We use the ObjectManager API
to enumerate paired devices across all adapters, and subscribe to
PropertiesChanged on org.bluez.Device1 for reactive UI.

Construct after the GLib mainloop is integrated with dbus
(see services/mpris.start_glib_loop), so subscribers fire on the GLib
thread.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import dbus

log = logging.getLogger(__name__)

DEVICE_IFACE = "org.bluez.Device1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OBJ_MGR_IFACE = "org.freedesktop.DBus.ObjectManager"


class BluezService:
    def __init__(self):
        self._bus = dbus.SystemBus()
        self._lock = threading.Lock()
        self._subs: list[Callable[[], None]] = []

        # Any Device1 PropertiesChanged → fire subscribers. The handler
        # ignores the change details and just lets each subscriber re-query.
        self._bus.add_signal_receiver(
            self._on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPS_IFACE,
            arg0=DEVICE_IFACE,
        )
        # InterfacesAdded / InterfacesRemoved cover pair/unpair events.
        self._bus.add_signal_receiver(
            self._on_interfaces_changed,
            signal_name="InterfacesAdded",
            dbus_interface=OBJ_MGR_IFACE,
        )
        self._bus.add_signal_receiver(
            self._on_interfaces_changed,
            signal_name="InterfacesRemoved",
            dbus_interface=OBJ_MGR_IFACE,
        )

    # ─── public API ────────────────────────────────────────────────────────

    def paired_devices(self) -> list[dict]:
        """Returns [{path, name, address, connected, icon}, ...]."""
        try:
            mgr = dbus.Interface(
                self._bus.get_object("org.bluez", "/"), OBJ_MGR_IFACE
            )
            objects = mgr.GetManagedObjects()
        except dbus.DBusException:
            log.exception("bluez: GetManagedObjects failed")
            return []

        devices: list[dict] = []
        for path, ifaces in objects.items():
            dev = ifaces.get(DEVICE_IFACE)
            if not dev:
                continue
            if not bool(dev.get("Paired", False)):
                continue
            devices.append({
                "path": str(path),
                "name": str(dev.get("Name", "")) or str(dev.get("Address", "")),
                "address": str(dev.get("Address", "")),
                "connected": bool(dev.get("Connected", False)),
                "icon": str(dev.get("Icon", "")) or "bluetooth",
            })
        # Connected devices first, then alphabetical.
        devices.sort(key=lambda d: (not d["connected"], d["name"].lower()))
        return devices

    def connect(self, path: str) -> None:
        try:
            iface = dbus.Interface(self._bus.get_object("org.bluez", path), DEVICE_IFACE)
            iface.Connect()
        except dbus.DBusException:
            log.exception("bluez: Connect on %s failed", path)

    def disconnect(self, path: str) -> None:
        try:
            iface = dbus.Interface(self._bus.get_object("org.bluez", path), DEVICE_IFACE)
            iface.Disconnect()
        except dbus.DBusException:
            log.exception("bluez: Disconnect on %s failed", path)

    def toggle(self, path: str, currently_connected: bool) -> None:
        if currently_connected:
            self.disconnect(path)
        else:
            self.connect(path)

    # ─── subscriptions ────────────────────────────────────────────────────

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(cb)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(cb)
                except ValueError:
                    pass

        return unsubscribe

    def _fire(self) -> None:
        with self._lock:
            cbs = list(self._subs)
        for cb in cbs:
            try:
                cb()
            except Exception:
                log.exception("bluez subscriber raised")

    def _on_properties_changed(self, *args, **kwargs) -> None:
        self._fire()

    def _on_interfaces_changed(self, *args, **kwargs) -> None:
        self._fire()
