"""Stream Deck device wrapper.

Hides the python-elgato-streamdeck library behind a thin interface and
handles the linear-index ↔ (col, row) translation our config uses.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PIL.Image import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError

log = logging.getLogger(__name__)


def _is_disconnect(err: BaseException) -> bool:
    """True if a TransportError indicates the device is gone."""
    msg = str(err).lower()
    return "no hid device" in msg or "no such device" in msg


class DeckHandle:
    """Owns one open Stream Deck device."""

    def __init__(self, serial: str | None = None):
        decks = DeviceManager().enumerate()
        if not decks:
            raise RuntimeError("no Stream Deck devices found")

        chosen = None
        # Skip the serial-number probe when there's only one deck — feature
        # reports on this libhidapi backend can intermittently fail with -1
        # right after a previous daemon shutdown, and the check is
        # redundant when there's nothing to disambiguate.
        if serial is None or len(decks) == 1:
            chosen = decks[0]
            chosen.open()
        else:
            for d in decks:
                d.open()
                try:
                    matched = d.get_serial_number() == serial
                except Exception:
                    matched = False
                if matched:
                    chosen = d
                    break
                d.close()

        if chosen is None:
            raise RuntimeError(f"no Stream Deck with serial {serial!r}")

        self._deck = chosen
        self._serial = serial
        # Serializes multi-chunk HID writes (set_key_image, reset, brightness).
        # Without this, concurrent invalidates from different reactive
        # services interleave their image chunks on the wire and produce
        # scrambled keys.
        self._io_lock = threading.Lock()
        # Flipped to False when an HID write reports the device has gone.
        # The daemon watchdog reads this to decide whether to reconnect.
        self.connected: bool = True
        self.cols: int = chosen.KEY_COLS
        self.rows: int = chosen.KEY_ROWS
        self.key_count: int = chosen.key_count()
        fmt = chosen.key_image_format()
        self.key_size: tuple[int, int] = tuple(fmt["size"])  # type: ignore[assignment]
        try:
            log.info(
                "opened deck: %s, %dx%d, %d keys",
                chosen.deck_type(), self.cols, self.rows, self.key_count,
            )
        except Exception:
            log.info("opened deck: %dx%d, %d keys",
                     self.cols, self.rows, self.key_count)

    def _note_io_error(self, err: BaseException) -> None:
        """Record a disconnect and let the caller decide what to do."""
        if isinstance(err, TransportError) and _is_disconnect(err):
            if self.connected:
                log.warning("deck: HID write reports no device — marking disconnected")
            self.connected = False

    def set_brightness(self, percent: int) -> None:
        try:
            with self._io_lock:
                self._deck.set_brightness(max(0, min(100, percent)))
        except TransportError as e:
            self._note_io_error(e)

    def reset(self) -> None:
        try:
            with self._io_lock:
                self._deck.reset()
        except TransportError as e:
            self._note_io_error(e)

    def close(self) -> None:
        with self._io_lock:
            try:
                self._deck.reset()
            except Exception:
                pass
            try:
                self._deck.close()
            except Exception:
                pass

    def set_key_image(self, idx: int, image: Image | None) -> None:
        """Push a PIL image to a key. None blanks the key.

        Holds `_io_lock` for the duration of the multi-chunk HID write so
        concurrent calls from different threads don't interleave on the wire.
        Flags `self.connected = False` on a disconnect-style transport error
        so the daemon's watchdog can react; suppresses the exception so the
        caller doesn't have to catch it on every push.
        """
        try:
            if image is None:
                with self._io_lock:
                    self._deck.set_key_image(idx, None)  # type: ignore[arg-type]
                return
            # PILHelper.to_native_key_format does pure-CPU work; do it outside
            # the lock to keep contention short.
            native = PILHelper.to_native_key_format(self._deck, image)
            with self._io_lock:
                self._deck.set_key_image(idx, native)
        except TransportError as e:
            self._note_io_error(e)

    def set_key_callback(self, fn: Callable[[int, bool], None]) -> None:
        """Register a (key_idx, pressed) callback."""
        def _bridge(_deck, key_index: int, pressed: bool) -> None:
            try:
                fn(key_index, pressed)
            except Exception:
                log.exception("key callback raised")

        self._deck.set_key_callback(_bridge)
