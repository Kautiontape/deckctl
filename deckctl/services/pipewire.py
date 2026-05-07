"""PipeWire / WirePlumber client.

Owns a `pactl subscribe` subprocess for change-event delivery and shells
out to `wpctl` for queries and actions. Subscribers fire on any
sink/source change.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
from typing import Callable

log = logging.getLogger(__name__)

DEFAULT_SINK = "@DEFAULT_AUDIO_SINK@"
DEFAULT_SOURCE = "@DEFAULT_AUDIO_SOURCE@"

_VOLUME_RE = re.compile(r"Volume:\s+([\d.]+)")


class PipewireService:
    def __init__(self):
        self._subs: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._start()

    def _start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            log.warning("pactl not available; volume widgets won't be reactive")
            return
        self._reader = threading.Thread(
            target=self._read_loop, name="pactl-reader", daemon=True
        )
        self._reader.start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            # We don't care which sink/source — any change re-queries state.
            if "change" in line and ("sink" in line or "source" in line):
                self._fire()

    # ─── public API ────────────────────────────────────────────────────────

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Returns an unsubscribe function — call when the widget goes away."""
        with self._lock:
            self._subs.append(cb)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subs.remove(cb)
                except ValueError:
                    pass

        return unsubscribe

    def state(self, target: str = DEFAULT_SINK) -> tuple[float, bool]:
        """Returns (volume_fraction, muted). volume in [0.0, 1.5+]."""
        try:
            out = subprocess.check_output(
                ["wpctl", "get-volume", target],
                text=True,
                timeout=2,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return 0.0, False
        muted = "[MUTED]" in out
        m = _VOLUME_RE.search(out)
        vol = float(m.group(1)) if m else 0.0
        return vol, muted

    def adjust(self, delta_percent: int, target: str = DEFAULT_SINK) -> None:
        sign = "+" if delta_percent >= 0 else "-"
        arg = f"{abs(delta_percent)}%{sign}"
        # -l 1.0 caps at 100% so we don't blow speakers from a stray hold.
        self._run(["wpctl", "set-volume", "-l", "1.0", target, arg])

    def toggle_mute(self, target: str = DEFAULT_SINK) -> None:
        self._run(["wpctl", "set-mute", target, "toggle"])

    def set_default(self, sink_id: str) -> None:
        self._run(["wpctl", "set-default", sink_id])

    def audio_sinks(self) -> list[dict]:
        """Snapshot of available sinks: [{name, description, default}, ...].

        `name` is the stable PipeWire object name (use it for set_default_sink).
        `description` is the human-friendly label.
        """
        default_name = ""
        try:
            default_name = subprocess.check_output(
                ["pactl", "get-default-sink"], text=True, timeout=2
            ).strip()
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

        descriptions: dict[str, str] = {}
        try:
            long_out = subprocess.check_output(
                ["pactl", "list", "sinks"], text=True, timeout=2
            )
            current_name: str | None = None
            for line in long_out.splitlines():
                stripped = line.strip()
                if stripped.startswith("Name: "):
                    current_name = stripped[len("Name: "):]
                elif stripped.startswith("Description: ") and current_name:
                    descriptions[current_name] = stripped[len("Description: "):]
                    current_name = None
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        try:
            short_out = subprocess.check_output(
                ["pactl", "list", "sinks", "short"], text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

        sinks: list[dict] = []
        for line in short_out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1]
            sinks.append({
                "name": name,
                "description": descriptions.get(name, name),
                "default": name == default_name,
            })
        return sinks

    def set_default_sink(self, name: str) -> None:
        """Switch the default sink by stable name (e.g. 'bluez_output.…')."""
        self._run(["pactl", "set-default-sink", name])

    def audio_sources(self) -> list[dict]:
        """Snapshot of input sources (microphones, etc.).

        Same shape as audio_sinks(). Filters out monitor sources (which
        capture sink output, not real inputs) — those exist for every
        sink and would clutter the list.
        """
        default_name = ""
        try:
            default_name = subprocess.check_output(
                ["pactl", "get-default-source"], text=True, timeout=2
            ).strip()
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

        descriptions: dict[str, str] = {}
        monitors: set[str] = set()
        try:
            long_out = subprocess.check_output(
                ["pactl", "list", "sources"], text=True, timeout=2
            )
            current_name: str | None = None
            current_props: list[str] = []
            for line in long_out.splitlines():
                stripped = line.strip()
                if stripped.startswith("Source #") or stripped.startswith("Description: "):
                    pass
                if stripped.startswith("Name: "):
                    current_name = stripped[len("Name: "):]
                    current_props = []
                elif stripped.startswith("Description: ") and current_name:
                    descriptions[current_name] = stripped[len("Description: "):]
                elif stripped.startswith("Monitor of Sink:") and current_name:
                    # Remember sources flagged as a sink monitor so we drop them.
                    if "n/a" not in stripped.lower():
                        monitors.add(current_name)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        try:
            short_out = subprocess.check_output(
                ["pactl", "list", "sources", "short"], text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

        sources: list[dict] = []
        for line in short_out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1]
            if name in monitors or ".monitor" in name:
                continue
            sources.append({
                "name": name,
                "description": descriptions.get(name, name),
                "default": name == default_name,
            })
        return sources

    def set_default_source(self, name: str) -> None:
        """Switch the default source by stable name."""
        self._run(["pactl", "set-default-source", name])

    # ─── internals ─────────────────────────────────────────────────────────

    def _run(self, argv: list[str]) -> None:
        try:
            subprocess.run(argv, check=False, timeout=3)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            log.exception("pipewire: %s failed", argv[0])

    def _fire(self) -> None:
        with self._lock:
            cbs = list(self._subs)
        for cb in cbs:
            try:
                cb()
            except Exception:
                log.exception("pipewire subscriber raised")
