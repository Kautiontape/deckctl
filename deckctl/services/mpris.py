"""MPRIS D-Bus client.

Owns the session bus connection and dispatches state changes to widgets via
subscriptions. Album art is fetched on demand and cached by URL.

Threading: this service runs alongside a GLib MainLoop on a dedicated
thread (started by the daemon). All D-Bus calls happen on that loop;
widget callbacks fire on that thread, so widgets must do thread-safe
work or hand off to the deck via the push callback (which is thread-safe).
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from io import BytesIO
from typing import Callable
from urllib.parse import urlparse
from urllib.request import urlopen

import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from PIL import Image

log = logging.getLogger(__name__)

PLAYER_PREFIX = "org.mpris.MediaPlayer2."
PLAYER_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"


class _ArtCache:
    """Tiny LRU cache keyed by URL → PIL.Image."""

    def __init__(self, capacity: int = 16):
        self._cap = capacity
        self._lock = threading.Lock()
        self._data: OrderedDict[str, Image.Image] = OrderedDict()

    def get(self, url: str) -> Image.Image | None:
        with self._lock:
            img = self._data.get(url)
            if img is not None:
                self._data.move_to_end(url)
            return img

    def put(self, url: str, img: Image.Image) -> None:
        with self._lock:
            self._data[url] = img
            self._data.move_to_end(url)
            while len(self._data) > self._cap:
                self._data.popitem(last=False)


class MprisService:
    """One per daemon. Subscribes to PropertiesChanged + NameOwnerChanged.

    Construct after the GLib mainloop is integrated with dbus
    (`dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)`), so subscribers
    fire on the GLib thread.
    """

    def __init__(self):
        self._bus = dbus.SessionBus()
        # subscribers: player_name → list[callback]
        self._subs: dict[str, list[Callable[[], None]]] = {}
        self._art = _ArtCache()
        self._lock = threading.Lock()

        # PropertiesChanged for any sender; we filter on player name in the handler.
        self._bus.add_signal_receiver(
            self._on_properties_changed,
            signal_name="PropertiesChanged",
            dbus_interface=PROPS_IFACE,
            path=PLAYER_PATH,
            sender_keyword="sender",
        )
        # NameOwnerChanged so we know when a player appears or disappears.
        self._bus.add_signal_receiver(
            self._on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
        )

    # ─── public API ────────────────────────────────────────────────────────

    def subscribe(
        self, player_name: str, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback fired when this player's state changes.

        Returns an unsubscribe function the caller MUST call when the
        widget is going away (e.g. on page transition). Subscribers are
        held by identity, so passing the same callback twice and
        unsubscribing once leaves one registration.

        `player_name` is the short suffix, e.g. "Feishin" → bus name
        `org.mpris.MediaPlayer2.Feishin`.
        """
        with self._lock:
            self._subs.setdefault(player_name, []).append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs[player_name].remove(callback)
                except (KeyError, ValueError):
                    pass

        return unsubscribe

    def state(self, player_name: str) -> dict | None:
        """Snapshot of the player. None if the player isn't running."""
        bus_name = PLAYER_PREFIX + player_name
        try:
            obj = self._bus.get_object(bus_name, PLAYER_PATH)
            props = dbus.Interface(obj, PROPS_IFACE)
            status = str(props.Get(PLAYER_IFACE, "PlaybackStatus"))
            meta = props.Get(PLAYER_IFACE, "Metadata")
        except dbus.DBusException:
            return None

        def _first(v):
            try:
                return str(v[0]) if len(v) else ""
            except TypeError:
                return str(v)

        # Optional/extra props — default if the player doesn't expose them.
        try:
            shuffle = bool(props.Get(PLAYER_IFACE, "Shuffle"))
        except dbus.DBusException:
            shuffle = False
        try:
            loop_status = str(props.Get(PLAYER_IFACE, "LoopStatus"))
        except dbus.DBusException:
            loop_status = "None"

        title = str(meta.get("xesam:title", ""))
        artists = meta.get("xesam:artist", [])
        artist = _first(artists) if artists else ""
        album = str(meta.get("xesam:album", ""))
        art_url = str(meta.get("mpris:artUrl", ""))
        # mpris:trackid is a D-Bus object path; the last segment is the
        # backing-server track ID (Subsonic uses this for star calls etc.)
        trackid_path = str(meta.get("mpris:trackid", ""))
        track_id = trackid_path.rsplit("/", 1)[-1] if trackid_path else ""

        return {
            "title": title,
            "artist": artist,
            "album": album,
            "status": status,
            "art_url": art_url,
            "shuffle": shuffle,
            "loop_status": loop_status,
            "track_id": track_id,
        }

    def art(self, url: str) -> Image.Image | None:
        """Load album art (cached). Returns None if the fetch fails."""
        if not url:
            return None
        cached = self._art.get(url)
        if cached is not None:
            return cached
        try:
            parsed = urlparse(url)
            if parsed.scheme == "file":
                img = Image.open(parsed.path).convert("RGBA")
            elif parsed.scheme in ("http", "https"):
                with urlopen(url, timeout=3) as resp:
                    data = resp.read()
                img = Image.open(BytesIO(data)).convert("RGBA")
            else:
                log.warning("mpris: unsupported art scheme %r", parsed.scheme)
                return None
        except Exception:
            log.exception("mpris: art fetch failed for %s", url)
            return None
        self._art.put(url, img)
        return img

    def play_pause(self, player_name: str) -> None:
        self._call(player_name, "PlayPause")

    def next(self, player_name: str) -> None:
        self._call(player_name, "Next")

    def previous(self, player_name: str) -> None:
        self._call(player_name, "Previous")

    def set_shuffle(self, player_name: str, value: bool) -> None:
        self._set_property(player_name, "Shuffle", dbus.Boolean(value))

    def set_loop(self, player_name: str, value: str) -> None:
        # value: "None", "Track", or "Playlist"
        self._set_property(player_name, "LoopStatus", dbus.String(value))

    def cycle_loop(self, player_name: str) -> None:
        """None → Playlist → Track → None."""
        s = self.state(player_name)
        cur = s.get("loop_status", "None") if s else "None"
        nxt = {"None": "Playlist", "Playlist": "Track", "Track": "None"}.get(cur, "None")
        self.set_loop(player_name, nxt)

    def raise_player(self, player_name: str) -> None:
        """Bring the player's window to focus via MPRIS Raise()."""
        try:
            obj = self._bus.get_object(PLAYER_PREFIX + player_name, PLAYER_PATH)
            iface = dbus.Interface(obj, "org.mpris.MediaPlayer2")
            iface.Raise()
        except dbus.DBusException:
            log.exception("mpris: Raise() on %s failed", player_name)

    # ─── internals ─────────────────────────────────────────────────────────

    def _call(self, player_name: str, method: str) -> None:
        try:
            obj = self._bus.get_object(PLAYER_PREFIX + player_name, PLAYER_PATH)
            iface = dbus.Interface(obj, PLAYER_IFACE)
            iface.get_dbus_method(method)()
        except dbus.DBusException:
            log.exception("mpris: %s on %s failed", method, player_name)

    def _set_property(self, player_name: str, prop: str, value) -> None:
        try:
            obj = self._bus.get_object(PLAYER_PREFIX + player_name, PLAYER_PATH)
            props = dbus.Interface(obj, PROPS_IFACE)
            props.Set(PLAYER_IFACE, prop, value)
        except dbus.DBusException:
            log.exception("mpris: set %s on %s failed", prop, player_name)

    def _player_for_sender(self, sender: str | None) -> str | None:
        """Resolve the bus unique name back to a player short name."""
        if sender is None:
            return None
        proxy = self._bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
        iface = dbus.Interface(proxy, "org.freedesktop.DBus")
        try:
            for name in iface.ListNames():
                n = str(name)
                if not n.startswith(PLAYER_PREFIX):
                    continue
                try:
                    owner = str(iface.GetNameOwner(n))
                except dbus.DBusException:
                    continue
                if owner == sender:
                    return n.removeprefix(PLAYER_PREFIX)
        except dbus.DBusException:
            return None
        return None

    def _on_properties_changed(self, iface, changed, invalidated, sender=None):
        if str(iface) != PLAYER_IFACE:
            return
        player = self._player_for_sender(sender)
        if not player:
            return
        self._fire(player)

    def _on_name_owner_changed(self, name, old_owner, new_owner):
        n = str(name)
        if not n.startswith(PLAYER_PREFIX):
            return
        self._fire(n.removeprefix(PLAYER_PREFIX))

    def _fire(self, player_name: str) -> None:
        with self._lock:
            cbs = list(self._subs.get(player_name, []))
        for cb in cbs:
            try:
                cb()
            except Exception:
                log.exception("mpris subscriber raised")


def start_glib_loop() -> threading.Thread:
    """Spin up a GLib MainLoop on a daemon thread and integrate dbus with it.

    Must be called once before constructing MprisService.
    """
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    loop = GLib.MainLoop()
    t = threading.Thread(target=loop.run, name="glib-mainloop", daemon=True)
    t.start()
    return t
