"""Desktop light/dark preference via the XDG settings portal.

Reads `org.freedesktop.appearance` / `color-scheme` (0 = no preference,
1 = prefer dark, 2 = prefer light) and follows the portal's
`SettingChanged` signal, so the state stays right when something other
than the deck flips it (waybar, a script, gsettings by hand).

Read-only on purpose: the widget toggles by running a command (the
`dark-mode` script in the dotfiles), which also switches the GTK theme
and refreshes waybar. Tolerates the portal not running — state reads
return False.

Threading: signal callbacks fire on the GLib mainloop thread, same as
SwayncService.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import dbus

log = logging.getLogger(__name__)

PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SETTINGS_IFACE = "org.freedesktop.portal.Settings"
NAMESPACE = "org.freedesktop.appearance"
KEY = "color-scheme"
PREFER_DARK = 1


class ColorSchemeService:
    """One per daemon. Exposes is_dark() with reactive subscribe()."""

    def __init__(self):
        self._bus = dbus.SessionBus()
        self._subs: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._dark = False

        self._bus.add_signal_receiver(
            self._on_setting_changed,
            signal_name="SettingChanged",
            dbus_interface=SETTINGS_IFACE,
            path=PORTAL_PATH,
        )
        self._refresh_state()

    # ─── public API ────────────────────────────────────────────────────────

    def is_dark(self) -> bool:
        with self._lock:
            return self._dark

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
            obj = self._bus.get_object(PORTAL_NAME, PORTAL_PATH)
            iface = dbus.Interface(obj, SETTINGS_IFACE)
            value = iface.ReadOne(NAMESPACE, KEY)
        except dbus.DBusException:
            log.debug("color_scheme: portal ReadOne failed (probably not running)")
            return
        self._set_dark(int(value) == PREFER_DARK)

    def _on_setting_changed(self, namespace, key, value) -> None:
        if namespace == NAMESPACE and key == KEY:
            self._set_dark(int(value) == PREFER_DARK)

    def _set_dark(self, value: bool) -> None:
        with self._lock:
            changed = value != self._dark
            self._dark = value
            subs = list(self._subs) if changed else []
        for cb in subs:
            try:
                cb()
            except Exception:
                log.exception("color_scheme: subscriber raised")
