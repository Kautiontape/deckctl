"""Minimal sway IPC wrapper for the marks page.

Shell out to `swaymsg` for one-shot operations. We don't use sway's native
mark feature here — the deck's mark slots are tracked in our own state
file. This service provides the glue: read the focused window, focus a
specific con_id, and check whether a con_id still exists.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

log = logging.getLogger(__name__)


class SwayService:
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
