"""Tracks recently-focused sway windows for the deck's recents row.

Subscribes to the SwayService window-event stream. On `focus` events,
moves the window to the front of an MRU list (de-duping by con_id). On
`close` events, removes the window from the list. Capped to a small
history.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .sway import SwayService

log = logging.getLogger(__name__)

DEFAULT_HISTORY = 12


class RecentsService:
    def __init__(self, sway: "SwayService", max_history: int = DEFAULT_HISTORY):
        self.sway = sway
        self.max_history = max_history
        self._lock = threading.Lock()
        self._history: list[dict] = []  # newest first
        self._subs: list[Callable[[], None]] = []
        sub = getattr(sway, "subscribe_window_events", None)
        if sub is not None:
            sub(self._on_window_event)

    # ─── public API ────────────────────────────────────────────────────────

    def items(self) -> list[dict]:
        """MRU list, newest first."""
        with self._lock:
            return list(self._history)

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

    # ─── internals ─────────────────────────────────────────────────────────

    def _on_window_event(self, event: dict) -> None:
        change = event.get("change")
        container = event.get("container") or {}
        con_id = container.get("id")
        if con_id is None:
            return
        try:
            con_id_int = int(con_id)
        except (TypeError, ValueError):
            return

        changed = False
        if change == "focus":
            entry = {
                "con_id": con_id_int,
                "app_id": (
                    container.get("app_id")
                    or (container.get("window_properties") or {}).get("class")
                    or ""
                ),
                "name": (container.get("name") or "")[:40],
            }
            with self._lock:
                # Move-to-front, de-dup.
                self._history = [r for r in self._history if r["con_id"] != con_id_int]
                self._history.insert(0, entry)
                if len(self._history) > self.max_history:
                    self._history = self._history[: self.max_history]
                changed = True
        elif change == "close":
            with self._lock:
                before = len(self._history)
                self._history = [r for r in self._history if r["con_id"] != con_id_int]
                changed = len(self._history) != before
        if changed:
            self._fire()

    def _fire(self) -> None:
        with self._lock:
            cbs = list(self._subs)
        for cb in cbs:
            try:
                cb()
            except Exception:
                log.exception("recents subscriber raised")
