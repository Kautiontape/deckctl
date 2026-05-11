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
ADAPTER_IFACE = "org.bluez.Adapter1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
OBJ_MGR_IFACE = "org.freedesktop.DBus.ObjectManager"


class BluezService:
    def __init__(self):
        self._bus = dbus.SystemBus()
        self._lock = threading.Lock()
        self._subs: list[Callable[[], None]] = []
        self._discovering = False

        # Any Device1 PropertiesChanged → fire subscribers. The handler
        # ignores the change details and just lets each subscriber re-query.
        self._bus.add_signal_receiver(
            self._on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPS_IFACE,
            arg0=DEVICE_IFACE,
        )
        # Adapter1 PropertiesChanged covers Discovering toggling externally
        # (e.g. via bluetoothctl) so our scan button stays in sync.
        self._bus.add_signal_receiver(
            self._on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPS_IFACE,
            arg0=ADAPTER_IFACE,
        )
        # InterfacesAdded / InterfacesRemoved cover pair/unpair events
        # and discovered-device appearances during a scan.
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

    @property
    def discovering(self) -> bool:
        return self._discovering

    def devices(self) -> list[dict]:
        """Returns [{path, name, address, connected, paired, icon}, ...].

        Includes both paired devices and any currently-known unpaired ones
        (which only appear while a scan is in progress, or shortly after).
        """
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
            devices.append({
                "path": str(path),
                "name": str(dev.get("Name", "")) or str(dev.get("Address", "")),
                "address": str(dev.get("Address", "")),
                "connected": bool(dev.get("Connected", False)),
                "paired": bool(dev.get("Paired", False)),
                "icon": str(dev.get("Icon", "")) or "bluetooth",
            })
        # Paired first (connected ahead of disconnected), then discovered
        # unpaired devices. Alphabetical within each group.
        devices.sort(key=lambda d: (
            not d["paired"], not d["connected"], d["name"].lower(),
        ))
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

    def pair(self, path: str) -> None:
        """Pair with `path`, then connect. Runs in a background thread
        because Device1.Pair can block for many seconds while the agent
        negotiates."""
        def _go() -> None:
            try:
                iface = dbus.Interface(
                    self._bus.get_object("org.bluez", path), DEVICE_IFACE
                )
                iface.Pair()
            except dbus.DBusException:
                log.exception("bluez: Pair on %s failed", path)
                return
            try:
                iface = dbus.Interface(
                    self._bus.get_object("org.bluez", path), DEVICE_IFACE
                )
                iface.Connect()
            except dbus.DBusException:
                log.exception("bluez: Connect after pair on %s failed", path)
        threading.Thread(target=_go, name="bluez-pair", daemon=True).start()

    def remove_device(self, path: str) -> None:
        """Forget a device. Adapter1.RemoveDevice on the device's parent
        adapter — works for both paired and merely-discovered entries."""
        parent = path.rsplit("/", 1)[0]
        try:
            adapter = dbus.Interface(
                self._bus.get_object("org.bluez", parent), ADAPTER_IFACE
            )
            adapter.RemoveDevice(path)
        except dbus.DBusException:
            log.exception("bluez: RemoveDevice %s failed", path)

    def start_discovery(self) -> None:
        with self._lock:
            if self._discovering:
                return
        started = False
        for ap in self._adapter_paths():
            try:
                adapter = dbus.Interface(
                    self._bus.get_object("org.bluez", ap), ADAPTER_IFACE
                )
                adapter.StartDiscovery()
                started = True
            except dbus.DBusException:
                log.exception("bluez: StartDiscovery on %s failed", ap)
        if started:
            with self._lock:
                self._discovering = True
            self._fire()

    def stop_discovery(self) -> None:
        with self._lock:
            if not self._discovering:
                return
            self._discovering = False
        for ap in self._adapter_paths():
            try:
                adapter = dbus.Interface(
                    self._bus.get_object("org.bluez", ap), ADAPTER_IFACE
                )
                adapter.StopDiscovery()
            except dbus.DBusException:
                log.exception("bluez: StopDiscovery on %s failed", ap)
        self._fire()

    def _adapter_paths(self) -> list[str]:
        try:
            mgr = dbus.Interface(
                self._bus.get_object("org.bluez", "/"), OBJ_MGR_IFACE
            )
            objects = mgr.GetManagedObjects()
        except dbus.DBusException:
            log.exception("bluez: GetManagedObjects (adapters) failed")
            return []
        return [
            str(p) for p, ifaces in objects.items() if ADAPTER_IFACE in ifaces
        ]

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
