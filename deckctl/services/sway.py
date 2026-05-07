"""Minimal sway IPC wrapper for the marks page.

Shell out to `swaymsg` for one-shot operations. We don't use sway's native
mark feature here — the deck's mark slots are tracked in our own state
file. This service provides the glue: read the focused window, focus a
specific con_id, and check whether a con_id still exists.

Also runs a long-lived `swaymsg -t subscribe '["window"]'` in a worker
thread for window-lifecycle events. Subscribers receive the raw event
dict; consumers can filter by `change` (close/new/focus/…).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class SwayService:
    def __init__(self):
        self._subs: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._start_window_subscription()

    def _start_window_subscription(self) -> None:
        try:
            self._proc = subprocess.Popen(
                ["swaymsg", "-t", "subscribe", "-m", '["window"]'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            log.warning("swaymsg not available; window-event subscriptions inert")
            return
        self._reader = threading.Thread(
            target=self._read_loop, name="sway-window-reader", daemon=True,
        )
        self._reader.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._fire(event)

    def subscribe_window_events(
        self, cb: Callable[[dict], None]
    ) -> Callable[[], None]:
        with self._lock:
            self._subs.append(cb)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(cb)
                except ValueError:
                    pass

        return unsubscribe

    def _fire(self, event: dict) -> None:
        with self._lock:
            cbs = list(self._subs)
        for cb in cbs:
            try:
                cb(event)
            except Exception:
                log.exception("sway-event subscriber raised")

    @staticmethod
    def _swaymsg(args: list[str], expect_json: bool = False) -> Any:
        try:
            out = subprocess.check_output(
                ["swaymsg", *args],
                text=True,
                timeout=3,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            log.exception("swaymsg %s failed", args)
            return None
        if expect_json:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                log.exception("swaymsg %s returned non-JSON", args)
                return None
        return out

    def tree(self) -> dict | None:
        return self._swaymsg(["-t", "get_tree"], expect_json=True)

    def focused(self) -> dict | None:
        """Returns the currently focused container or None."""
        tree = self.tree()
        if tree is None:
            return None
        return _find(tree, lambda n: n.get("focused") is True)

    def find_con(self, con_id: int) -> dict | None:
        tree = self.tree()
        if tree is None:
            return None
        return _find(tree, lambda n: n.get("id") == con_id)

    def focus_con(self, con_id: int) -> None:
        # Bring scratchpadded windows back; if it's already on a workspace
        # this is a no-op floating-wise but the focus still applies.
        cmd = (
            f"[con_id={con_id}] move window to workspace current, "
            f"focus, floating enable"
        )
        self._swaymsg([cmd])

    def bury_con(self, con_id: int) -> None:
        """Send a window to sway's global scratchpad."""
        self._swaymsg([f"[con_id={con_id}] move scratchpad"])

    def is_visible(self, con_id: int) -> bool:
        """True if the window is currently on a workspace; False if hidden in scratchpad."""
        node = self.find_con(con_id)
        if node is None:
            return False
        return bool(node.get("visible"))


def _find(node: dict, pred) -> dict | None:
    if pred(node):
        return node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        hit = _find(child, pred)
        if hit is not None:
            return hit
    return None
