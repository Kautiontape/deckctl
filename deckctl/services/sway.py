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
        self._lock = threading.Lock()
        # Per-event-type subscribers. swaymsg events don't include a
        # discriminator in their JSON, so we keep a separate subprocess
        # per event class.
        self._subs: dict[str, list[Callable[[dict], None]]] = {
            "window": [],
            "workspace": [],
        }
        self._procs: dict[str, subprocess.Popen] = {}
        self._start_subscription("window")
        self._start_subscription("workspace")

    def _start_subscription(self, event_type: str) -> None:
        try:
            proc = subprocess.Popen(
                ["swaymsg", "-t", "subscribe", "-m", f'["{event_type}"]'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            log.warning("swaymsg not available; %s-event subscriptions inert",
                        event_type)
            return
        self._procs[event_type] = proc
        threading.Thread(
            target=self._read_loop,
            args=(event_type, proc),
            name=f"sway-{event_type}-reader",
            daemon=True,
        ).start()

    def _read_loop(self, event_type: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._fire(event_type, event)

    def subscribe_window_events(
        self, cb: Callable[[dict], None]
    ) -> Callable[[], None]:
        return self._subscribe("window", cb)

    def subscribe_workspace_events(
        self, cb: Callable[[dict], None]
    ) -> Callable[[], None]:
        return self._subscribe("workspace", cb)

    def _subscribe(
        self, event_type: str, cb: Callable[[dict], None]
    ) -> Callable[[], None]:
        with self._lock:
            self._subs[event_type].append(cb)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs[event_type].remove(cb)
                except ValueError:
                    pass

        return unsubscribe

    def _fire(self, event_type: str, event: dict) -> None:
        with self._lock:
            cbs = list(self._subs[event_type])
        for cb in cbs:
            try:
                cb(event)
            except Exception:
                log.exception("sway %s-event subscriber raised", event_type)

    def current_workspace(self) -> int | None:
        """Returns the focused workspace number, or None on failure."""
        ws = self._swaymsg(["-t", "get_workspaces"], expect_json=True)
        if not isinstance(ws, list):
            return None
        for w in ws:
            if w.get("focused"):
                num = w.get("num")
                if isinstance(num, int):
                    return num
        return None

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
