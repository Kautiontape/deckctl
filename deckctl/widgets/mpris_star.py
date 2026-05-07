"""`mpris_star` widget — Subsonic star toggle for the current MPRIS track."""

from __future__ import annotations

import logging
import threading

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("mpris_star")
class MprisStarWidget:
    def __init__(self, settings: dict, deps: WidgetDeps):
        self.player: str = settings.get("player", "Feishin")
        self._deps = deps
        self.invalidate = None
        self._unsub = None
        # Cached starred state for the currently-displayed track. Avoids a
        # Subsonic round-trip on every render. Refreshed on track change.
        self._lock = threading.Lock()
        self._cached_track_id: str | None = None
        self._cached_starred: bool = False
        if deps.mpris is not None:
            self._unsub = deps.mpris.subscribe(self.player, self._on_change)
        # Prime the cache on a worker thread so the first render is right.
        threading.Thread(target=self._refresh_cache, daemon=True).start()

    def _current_track_id(self) -> str:
        if self._deps.mpris is None:
            return ""
        s = self._deps.mpris.state(self.player)
        return s.get("track_id", "") if s else ""

    def _refresh_cache(self) -> None:
        sub = getattr(self._deps, "subsonic", None)
        if sub is None:
            return
        tid = self._current_track_id()
        starred = sub.is_starred(tid) if tid else False
        with self._lock:
            self._cached_track_id = tid
            self._cached_starred = starred
        cb = self.invalidate
        if cb is not None:
            cb()

    def render(self) -> Image:
        with self._lock:
            starred = self._cached_starred
            cached_id = self._cached_track_id
        # If track has changed since last cache fill, kick a refresh.
        if cached_id != self._current_track_id():
            threading.Thread(target=self._refresh_cache, daemon=True).start()
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon="starred" if starred else "non-starred",
            label="Starred" if starred else "Star",
            font_family=self._deps.font,
            bg=(60, 50, 10) if starred else (0, 0, 0),
            fg=(255, 220, 80) if starred else (200, 200, 200),
        )

    def on_press(self, ctx) -> None:
        sub = getattr(self._deps, "subsonic", None)
        if sub is None:
            log.warning("mpris_star: SubsonicService not initialized")
            return
        tid = self._current_track_id()
        if not tid:
            return
        with self._lock:
            currently = (self._cached_track_id == tid) and self._cached_starred
        # Optimistic local flip + invalidate; refresh from server on a worker.
        with self._lock:
            self._cached_track_id = tid
            self._cached_starred = not currently
        cb = self.invalidate
        if cb is not None:
            cb()

        def _commit():
            ok = sub.unstar(tid) if currently else sub.star(tid)
            if not ok:
                # Revert on failure.
                with self._lock:
                    self._cached_starred = currently
                cb2 = self.invalidate
                if cb2 is not None:
                    cb2()
        threading.Thread(target=_commit, daemon=True).start()

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    def _on_change(self) -> None:
        # Track may have changed; re-prime cache then redraw.
        threading.Thread(target=self._refresh_cache, daemon=True).start()

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self.invalidate = None
