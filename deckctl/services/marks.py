"""Deck-side mark slots — independent of sway's native marks and the
letter-based marks managed by sway-mark.sh.

State lives in /tmp/deckctl-marks.json. Each of N_SLOTS slots holds either
a {con_id, app_id, name} dict or null. The MarksService also owns the
"assign mode" UI state shared between the marks-page widgets.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .sway import SwayService

log = logging.getLogger(__name__)

N_SLOTS = 12
DEFAULT_STATE_PATH = Path("/tmp/deckctl-marks.json")


class MarksService:
    def __init__(self, sway: "SwayService", state_path: Path = DEFAULT_STATE_PATH):
        self.sway = sway
        self.state_path = state_path
        self._lock = threading.Lock()
        self._slots: dict[int, dict | None] = {i: None for i in range(1, N_SLOTS + 1)}
        self._assign_mode: bool = False
        self._subs: list[Callable[[], None]] = []
        self._load()

    # ─── public state ─────────────────────────────────────────────────────

    @property
    def assign_mode(self) -> bool:
        return self._assign_mode

    def slot(self, n: int) -> dict | None:
        return self._slots.get(n)

    def all_slots(self) -> dict[int, dict | None]:
        return dict(self._slots)

    # ─── operations ───────────────────────────────────────────────────────

    def set_assign_mode(self, value: bool) -> None:
        if self._assign_mode == value:
            return
        self._assign_mode = value
        self._fire()

    def assign(self, slot: int, con_id: int, app_id: str, name: str) -> None:
        """Place the given window in `slot`, replacing any existing entry."""
        if not (1 <= slot <= N_SLOTS):
            return
        self._slots[slot] = {
            "con_id": int(con_id),
            "app_id": app_id or "",
            "name": (name or "")[:40],
        }
        self._save()
        self._fire()

    def clear(self, slot: int) -> None:
        if not (1 <= slot <= N_SLOTS):
            return
        if self._slots[slot] is None:
            return
        self._slots[slot] = None
        self._save()
        self._fire()

    def activate(self, slot: int) -> bool:
        """Toggle the window in `slot` between visible and scratchpad-buried.

        Returns True if a window was acted on. If the window is currently
        visible on a workspace, this buries it (moves to scratchpad). If
        it's hidden in scratchpad (or just not currently focused on a
        visible workspace), this brings it back. Stale slots are cleared.
        """
        info = self._slots.get(slot)
        if not info:
            return False
        con_id = int(info["con_id"])
        node = self.sway.find_con(con_id)
        if node is None:
            log.info("marks: slot %d con_id=%d is stale; clearing", slot, con_id)
            self.clear(slot)
            return False
        if node.get("visible"):
            self.sway.bury_con(con_id)
        else:
            self.sway.focus_con(con_id)
        # No state change persists in our slot file (only sway tree changes),
        # but we fire so any UI that wants to reflect visibility can re-render.
        self._fire()
        return True

    def assign_focused(self, slot: int) -> bool:
        """Place the currently focused window in `slot`. Returns True on success."""
        focused = self.sway.focused()
        if focused is None:
            log.warning("marks: no focused window to assign")
            return False
        con_id = int(focused.get("id", 0))
        if not con_id:
            return False
        app_id = focused.get("app_id") or focused.get(
            "window_properties", {}
        ).get("class") or ""
        name = focused.get("name") or ""
        self.assign(slot, con_id, app_id, name)
        return True

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
                log.exception("marks subscriber raised")

    # ─── persistence ──────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            log.exception("marks: load failed; starting fresh")
            return
        for k, v in data.items():
            try:
                slot = int(k)
            except ValueError:
                continue
            if 1 <= slot <= N_SLOTS:
                self._slots[slot] = v if isinstance(v, dict) else None

    def _save(self) -> None:
        try:
            self.state_path.write_text(
                json.dumps({str(k): v for k, v in self._slots.items()}, indent=2)
            )
        except OSError:
            log.exception("marks: save failed")
