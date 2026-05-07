"""Stream Deck device wrapper.

Hides the python-elgato-streamdeck library behind a thin interface and
handles the linear-index ↔ (col, row) translation our config uses.
"""

from __future__ import annotations

import logging
from typing import Callable

from PIL.Image import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

log = logging.getLogger(__name__)


class DeckHandle:
    """Owns one open Stream Deck device."""

    def __init__(self, serial: str | None = None):
        decks = DeviceManager().enumerate()
        if not decks:
            raise RuntimeError("no Stream Deck devices found")

        chosen = None
        if serial is not None:
            for d in decks:
                d.open()
                try:
                    if d.get_serial_number() == serial:
                        chosen = d
                        break
                finally:
                    if chosen is not d:
                        d.close()
        else:
            chosen = decks[0]
            chosen.open()

        if chosen is None:
            raise RuntimeError(f"no Stream Deck with serial {serial!r}")

        self._deck = chosen
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

    def set_brightness(self, percent: int) -> None:
        self._deck.set_brightness(max(0, min(100, percent)))

    def reset(self) -> None:
        self._deck.reset()

    def close(self) -> None:
        try:
            self._deck.reset()
        except Exception:
            pass
        try:
            self._deck.close()
        except Exception:
            pass

    def set_key_image(self, idx: int, image: Image | None) -> None:
        """Push a PIL image to a key. None blanks the key."""
        if image is None:
            self._deck.set_key_image(idx, None)  # type: ignore[arg-type]
            return
        native = PILHelper.to_native_key_format(self._deck, image)
        self._deck.set_key_image(idx, native)

    def set_key_callback(self, fn: Callable[[int, bool], None]) -> None:
        """Register a (key_idx, pressed) callback."""
        def _bridge(_deck, key_index: int, pressed: bool) -> None:
            try:
                fn(key_index, pressed)
            except Exception:
                log.exception("key callback raised")

        self._deck.set_key_callback(_bridge)
