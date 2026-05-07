"""Page stack and the active-page renderer.

The PageStack tracks navigation history. The ActivePage owns widget instances
for the currently displayed page and is responsible for drawing them onto
the deck.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .config import DeckConfig, KeyDef, PageDef
from .icons import IconResolver
from .render import overlay_progress_arc
from .widgets import Widget, WidgetDeps, build

log = logging.getLogger(__name__)


class PageStack:
    """Push/pop navigation. Always contains at least one page."""

    def __init__(
        self,
        pages: dict[str, PageDef],
        deck_cfg: DeckConfig,
        on_change: Callable[[PageDef], None],
    ):
        if deck_cfg.default_page not in pages:
            raise ValueError(
                f"default_page {deck_cfg.default_page!r} not in {sorted(pages)}"
            )
        self._pages = pages
        self._cfg = deck_cfg
        self._on_change = on_change
        self._stack: list[str] = [deck_cfg.default_page]
        self._on_change(pages[deck_cfg.default_page])

    @property
    def current(self) -> PageDef:
        return self._pages[self._stack[-1]]

    def push(self, name: str) -> None:
        if name not in self._pages:
            log.warning("push to unknown page %r — ignoring", name)
            return
        if self._stack[-1] == name:
            return
        self._stack.append(name)
        self._on_change(self.current)

    def back(self) -> None:
        if len(self._stack) > 1:
            self._stack.pop()
            self._on_change(self.current)
            return
        # No history. Fall back to the page's declared `back`, then default.
        cur = self.current
        if cur.back and cur.back in self._pages and cur.back != cur.name:
            self._stack[-1] = cur.back
            self._on_change(self.current)
            return
        if (
            self._cfg.default_page != cur.name
            and self._cfg.default_page in self._pages
        ):
            self._stack[-1] = self._cfg.default_page
            self._on_change(self.current)


class ActivePage:
    """Holds widget instances for the current page; routes key events.

    `push` is invoked by reactive widgets via their `invalidate` callback to
    push a freshly-rendered key image to the deck. The daemon supplies it.
    """

    def __init__(
        self,
        page: PageDef,
        deck_cols: int,
        deck_rows: int,
        deps: WidgetDeps,
        push: Callable[[int, "object"], None] | None = None,
        long_press_default_ms: int = 800,
    ):
        self.page = page
        self.cols = deck_cols
        self.rows = deck_rows
        self.long_press_default_ms = long_press_default_ms
        self._push = push
        self._deps = deps
        # widgets keyed by linear key index
        self.widgets: dict[int, Widget] = {}
        self.long_press_ms: dict[int, int] = {}
        # Indices whose `long_press_ms` was explicitly set in TOML (i.e.
        # a real long-press gate, not the implicit default). Only those
        # get the progress-ring animation.
        self._long_press_explicit: set[int] = set()
        self._press_starts: dict[int, float] = {}
        # Per-key threads that animate a progress ring during a held press.
        self._press_anim_stops: dict[int, threading.Event] = {}
        # Dynamic regions: each holds its own producer subscription and
        # tracks which indices it currently owns so it can rebuild.
        self._regions: list[_DynamicRegion] = []

        for kdef in page.keys:
            if kdef.type == "dynamic":
                region = _DynamicRegion(kdef, self)
                self._regions.append(region)
                region.expand()
                continue
            self._add_widget(kdef)

    def _add_widget(self, kdef: KeyDef) -> int | None:
        col, row = kdef.pos
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            log.warning("page %s: pos %s out of range", self.page.name, kdef.pos)
            return None
        idx = row * self.cols + col
        try:
            w = build(kdef, self._deps)
        except Exception:
            log.exception(
                "page %s pos %s: failed to build widget %r",
                self.page.name, kdef.pos, kdef.type,
            )
            return None
        self.widgets[idx] = w
        self.long_press_ms[idx] = int(
            kdef.settings.get("long_press_ms", self.long_press_default_ms)
        )
        # A key opts into the progress-ring animation by declaring either
        # `long_press_ms` (a hold-to-confirm gate) or `on_long_press` (a
        # distinct long-press action) in its TOML.
        if "long_press_ms" in kdef.settings or "on_long_press" in kdef.settings:
            self._long_press_explicit.add(idx)
        w.invalidate = self._invalidator_for(idx, w)
        return idx

    def _remove_widget(self, idx: int) -> None:
        w = self.widgets.pop(idx, None)
        self.long_press_ms.pop(idx, None)
        self._long_press_explicit.discard(idx)
        if w is None:
            return
        disp = getattr(w, "dispose", None)
        if disp is not None:
            try:
                disp()
            except Exception:
                log.exception("widget dispose at idx %d raised", idx)

    def dispose(self) -> None:
        """Tear down widgets so they unsubscribe from services and stop threads.

        Called by the daemon when this page is being replaced. Idempotent.
        """
        for region in self._regions:
            region.dispose()
        self._regions.clear()
        for idx, w in list(self.widgets.items()):
            disp = getattr(w, "dispose", None)
            if disp is None:
                continue
            try:
                disp()
            except Exception:
                log.exception("widget dispose at idx %d raised", idx)
        self.widgets.clear()

    def _invalidator_for(self, idx: int, widget: Widget) -> Callable[[], None]:
        push = self._push
        if push is None:
            return lambda: None

        def invalidate() -> None:
            try:
                img = widget.render()
            except Exception:
                log.exception("widget render failed during invalidate at idx %d", idx)
                return
            try:
                push(idx, img)
            except Exception:
                log.exception("push failed at idx %d", idx)

        return invalidate

    def render(self) -> dict[int, "object"]:
        """Render all configured keys. Returns idx → PIL.Image."""
        out: dict[int, object] = {}
        for idx, w in self.widgets.items():
            try:
                out[idx] = w.render()
            except Exception:
                log.exception("widget render failed at idx %d", idx)
        return out

    def handle_press(self, idx: int) -> None:
        self._press_starts[idx] = time.monotonic()
        threshold = self.long_press_ms.get(idx, self.long_press_default_ms)
        # Only animate on keys that explicitly opted into a long-press gate.
        # All other keys keep the default threshold but get no visual arc,
        # avoiding a flash on routine taps.
        if idx in self._long_press_explicit and self._push is not None:
            stop = threading.Event()
            self._press_anim_stops[idx] = stop
            threading.Thread(
                target=self._animate_press,
                args=(idx, threshold, stop),
                name=f"press-anim-{idx}",
                daemon=True,
            ).start()

    def handle_release(self, idx: int, ctx) -> None:
        started = self._press_starts.pop(idx, None)
        stop = self._press_anim_stops.pop(idx, None)
        had_animation = stop is not None
        if stop is not None:
            stop.set()
        widget = self.widgets.get(idx)
        if widget is None:
            return
        held_ms = (
            int((time.monotonic() - started) * 1000) if started is not None else 0
        )
        threshold = self.long_press_ms.get(idx, self.long_press_default_ms)
        try:
            if held_ms >= threshold:
                widget.on_long_press(ctx)
            else:
                widget.on_press(ctx)
        except Exception:
            log.exception("widget action raised at idx %d", idx)
        # Only restore the widget's base render if we'd actually drawn an
        # arc on top — otherwise the deck already shows the right image
        # and the extra push is wasted (and could flicker reactive widgets).
        if had_animation and self._push is not None:
            try:
                self._push(idx, widget.render())
            except Exception:
                log.exception("widget render after release at idx %d", idx)

    def _animate_press(self, idx: int, threshold_ms: int, stop: threading.Event) -> None:
        """Push a progress-arc-overlaid frame at ~20Hz while a key is held."""
        push = self._push
        if push is None:
            return
        widget = self.widgets.get(idx)
        if widget is None:
            return
        started = self._press_starts.get(idx)
        if started is None:
            return
        last_progress = -1.0
        while not stop.is_set():
            elapsed_ms = (time.monotonic() - started) * 1000
            progress = min(1.0, elapsed_ms / threshold_ms)
            # Skip redraw if visually unchanged (within 2% of last frame).
            if abs(progress - last_progress) >= 0.02:
                last_progress = progress
                try:
                    base = widget.render()
                    push(idx, overlay_progress_arc(base, progress))
                except Exception:
                    log.exception("press anim render at idx %d", idx)
            if progress >= 1.0:
                break
            stop.wait(0.05)


class _DynamicRegion:
    """One dynamic-list region inside an ActivePage.

    Resolves a producer from deps, materializes its items into widgets at
    sequential positions starting at `kdef.pos`, and re-builds whenever
    the producer fires its subscription callback.
    """

    def __init__(self, kdef: KeyDef, page: "ActivePage"):
        self.kdef = kdef
        self.page = page
        producer_name = kdef.settings.get("producer", "")
        producers = getattr(page._deps, "producers", None) or {}
        self.producer = producers.get(producer_name)
        if self.producer is None:
            log.warning(
                "dynamic: producer %r not registered (known: %s)",
                producer_name, sorted(producers),
            )
        self.slots = max(1, int(kdef.settings.get("slots", 1)))
        self.start_col, self.start_row = kdef.pos
        self.indices: list[int] = []
        self._unsub = None
        if self.producer is not None:
            self._unsub = self.producer.subscribe(self._on_change)

    def _slot_indices(self) -> list[int]:
        """All positions this region MAY occupy (row-wrapping at deck width)."""
        out: list[int] = []
        for offset in range(self.slots):
            linear = self.start_row * self.page.cols + self.start_col + offset
            row = linear // self.page.cols
            if row >= self.page.rows:
                break
            out.append(linear)
        return out

    def expand(self) -> None:
        """Build widgets for the current items. Push images for changed slots."""
        if self.producer is None:
            return
        try:
            items = self.producer.items()
        except Exception:
            log.exception("dynamic: producer %r .items() raised", self.kdef.settings)
            items = []

        slot_indices = self._slot_indices()
        new_indices: list[int] = []
        for idx, item in zip(slot_indices, items):
            kdef = KeyDef(
                pos=(idx % self.page.cols, idx // self.page.cols),
                type=item.widget_type,
                settings=dict(item.settings),
            )
            placed = self.page._add_widget(kdef)
            if placed is not None:
                new_indices.append(placed)
        self.indices = new_indices

        # Push images for newly-placed widgets.
        if self.page._push is not None:
            for idx in new_indices:
                w = self.page.widgets.get(idx)
                if w is None:
                    continue
                try:
                    img = w.render()
                except Exception:
                    log.exception("dynamic: render at idx %d", idx)
                    continue
                self.page._push(idx, img)
            # Blank any reserved slots that no longer have an item.
            for idx in slot_indices:
                if idx not in new_indices:
                    self.page._push(idx, None)

    def _on_change(self) -> None:
        # Tear down current widgets, then re-expand. Both happen on the
        # producer's dispatch thread, which is fine — set_key_image is
        # serialized through DeckHandle._io_lock.
        for idx in list(self.indices):
            self.page._remove_widget(idx)
        self.indices.clear()
        self.expand()

    def dispose(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None


def make_widget_deps(deck_cfg: DeckConfig, key_size: tuple[int, int]) -> WidgetDeps:
    return WidgetDeps(
        icons=IconResolver(deck_cfg.icon_dirs),
        key_size=key_size,
        font=deck_cfg.font,
    )
