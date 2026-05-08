"""SwayNC (notification daemon) DBus client.

Reactive `dnd` state via the `org.erikreider.swaync.cc.SubscribeV2` signal,
plus a toggle method that calls `ToggleDnd`. Tolerates swaync not being
running — calls become no-ops, state reads return False.

Threading: lives on the GLib mainloop thread (same as MprisService); the
DBus session bus connection is shared. Subscriber callbacks fire on that
thread.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import dbus

log = logging.getLogger(__name__)

SWAYNC_NAME = "org.erikreider.swaync.cc"
SWAYNC_PATH = "/org/erikreider/swaync/cc"
SWAYNC_IFACE = "org.erikreider.swaync.cc"


class SwayncService:
    """One per daemon. Exposes DND state with reactive subscribe()."""

    def __init__(self):
        self._bus = dbus.SessionBus()
        self._subs: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._dnd = False

        # Listen for swaync's status broadcasts. SubscribeV2 fires on every
        # change (count/dnd/cc_open/inhibited); we only care about dnd.
        self._bus.add_signal_receiver(
            self._on_subscribe_v2,
            signal_name="SubscribeV2",
            dbus_interface=SWAYNC_IFACE,
            path=SWAYNC_PATH,
        )
        # Also handle the older Subscribe signal in case we ever talk to a
        # build that only emits that one.
        self._bus.add_signal_receiver(
            self._on_subscribe_v1,
            signal_name="Subscribe",
            dbus_interface=SWAYNC_IFACE,
            path=SWAYNC_PATH,
        )

        # Prime initial state. If swaync isn't up, this just leaves False.
        self._refresh_state()

    # ─── public API ────────────────────────────────────────────────────────

    def get_dnd(self) -> bool:
        with self._lock:
            return self._dnd

    def toggle_dnd(self) -> None:
        try:
            obj = self._bus.get_object(SWAYNC_NAME, SWAYNC_PATH)
            iface = dbus.Interface(obj, SWAYNC_IFACE)
            new_state = bool(iface.ToggleDnd())
        except dbus.DBusException as e:
            log.warning("swaync: ToggleDnd failed: %s", e)
            return
        # Apply immediately so the UI updates even if the signal is slow.
        self._set_dnd(new_state)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            self._subs.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    # ─── internals ────────────────────────────────────────────────────────

    def _refresh_state(self) -> None:
        try:
            obj = self._bus.get_object(SWAYNC_NAME, SWAYNC_PATH)
            iface = dbus.Interface(obj, SWAYNC_IFACE)
            self._set_dnd(bool(iface.GetDnd()))
        except dbus.DBusException:
            log.debug("swaync: GetDnd failed (probably not running)")

    def _set_dnd(self, value: bool) -> None:
        with self._lock:
            changed = value != self._dnd
            self._dnd = value
            subs = list(self._subs) if changed else []
        for cb in subs:
            try:
                cb()
            except Exception:
                log.exception("swaync: subscriber raised")

    def _on_subscribe_v2(self, count, dnd, cc_open, inhibited) -> None:  # noqa: ARG002
        self._set_dnd(bool(dnd))

    def _on_subscribe_v1(self, count, dnd, cc_open) -> None:  # noqa: ARG002
        self._set_dnd(bool(dnd))
