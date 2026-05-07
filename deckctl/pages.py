"""Page stack and the active-page renderer.

The PageStack tracks navigation history. The ActivePage owns widget instances
for the currently displayed page and is responsible for drawing them onto
the deck.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from .config import DeckConfig, PageDef
from .icons import IconResolver
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
        # widgets keyed by linear key index
        self.widgets: dict[int, Widget] = {}
        self.long_press_ms: dict[int, int] = {}
        self._press_starts: dict[int, float] = {}

        for kdef in page.keys:
            col, row = kdef.pos
            if not (0 <= col < deck_cols and 0 <= row < deck_rows):
                log.warning("page %s: pos %s out of range", page.name, kdef.pos)
                continue
            idx = row * deck_cols + col
            try:
                w = build(kdef, deps)
            except Exception:
                log.exception("page %s pos %s: failed to build widget %r",
                              page.name, kdef.pos, kdef.type)
                continue
            self.widgets[idx] = w
            self.long_press_ms[idx] = int(
                kdef.settings.get("long_press_ms", long_press_default_ms)
            )
            # Bind invalidate so reactive widgets can update themselves.
            w.invalidate = self._invalidator_for(idx, w)

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

    def handle_release(self, idx: int, ctx) -> None:
        started = self._press_starts.pop(idx, None)
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


def make_widget_deps(deck_cfg: DeckConfig, key_size: tuple[int, int]) -> WidgetDeps:
    return WidgetDeps(
        icons=IconResolver(deck_cfg.icon_dirs),
        key_size=key_size,
        font=deck_cfg.font,
    )
