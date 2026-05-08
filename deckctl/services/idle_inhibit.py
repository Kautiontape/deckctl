"""Manual idle/sleep inhibitor.

Holds a long-running `systemd-inhibit ... sleep infinity` subprocess while
active. Blocks `systemctl suspend` (which is what swayidle eventually fires
in our config), so flipping this on parks the machine until you flip it off.

Activates the lock at the systemd level — `loginctl list-inhibitors` will
show it. We don't try to share this state with Waybar's per-instance
Wayland idle inhibitor; the deck button is the source of truth for our
own inhibitor.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Callable

log = logging.getLogger(__name__)


class IdleInhibitService:
    """Owns the inhibit subprocess. Subscribers get notified on toggle."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._subs: list[Callable[[], None]] = []
        self._available = shutil.which("systemd-inhibit") is not None
        if not self._available:
            log.warning(
                "idle_inhibit: systemd-inhibit not found; toggle will be inert"
            )

    @property
    def available(self) -> bool:
        return self._available

    # ─── public API ────────────────────────────────────────────────────────

    def is_inhibited(self) -> bool:
        with self._lock:
            proc = self._proc
            if proc is None:
                return False
            # poll() is None while running.
            if proc.poll() is None:
                return True
            # Process died on us; clean up.
            self._proc = None
            return False

    def set_inhibited(self, value: bool) -> None:
        with self._lock:
            currently = self._proc is not None and self._proc.poll() is None
            if value and not currently:
                self._spawn_locked()
            elif not value and self._proc is not None:
                self._kill_locked()
            else:
                return  # no change
            new_state = self._proc is not None and self._proc.poll() is None
            subs = list(self._subs)
        log.info("idle_inhibit: %s", "on" if new_state else "off")
        for cb in subs:
            try:
                cb()
            except Exception:
                log.exception("idle_inhibit: subscriber raised")

    def toggle(self) -> None:
        self.set_inhibited(not self.is_inhibited())

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

    def shutdown(self) -> None:
        """Drop the inhibitor when the daemon exits — don't leak it."""
        with self._lock:
            if self._proc is not None:
                self._kill_locked()

    # ─── internals (caller holds _lock) ───────────────────────────────────

    def _spawn_locked(self) -> None:
        if not self._available:
            return
        try:
            self._proc = subprocess.Popen(
                [
                    "systemd-inhibit",
                    "--what=sleep:idle",
                    "--who=deckctl",
                    "--why=Manual idle/sleep hold",
                    "--mode=block",
                    "sleep", "infinity",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            log.exception("idle_inhibit: failed to spawn systemd-inhibit")
            self._proc = None

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1)
        except Exception:
            log.exception("idle_inhibit: error while terminating subprocess")
