"""deckctl daemon entrypoint."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from .actions import ActionContext
from .config import DeckConfig, PageDef, load_deck_config, load_pages, load_secrets
from .deck import DeckHandle
from .pages import ActivePage, PageStack, make_widget_deps
from .services.mpris import MprisService, start_glib_loop
from .services.pipewire import PipewireService

log = logging.getLogger("deckctl")


class Daemon:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.deck: DeckHandle | None = None
        self.cfg: DeckConfig | None = None
        self.pages: dict[str, PageDef] = {}
        self.secrets: dict[str, str] = {}
        self.page_stack: PageStack | None = None
        self.active: ActivePage | None = None
        self.mpris: MprisService | None = None
        self.pipewire: PipewireService | None = None
        self._stop = threading.Event()
        self._reload_lock = threading.Lock()

    # ─── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._load_config()
        assert self.cfg is not None
        # GLib + dbus must be set up before MprisService.
        start_glib_loop()
        try:
            self.mpris = MprisService()
        except Exception:
            log.exception("mpris init failed; mpris widgets will be inert")
            self.mpris = None
        try:
            self.pipewire = PipewireService()
        except Exception:
            log.exception("pipewire init failed; volume/mic widgets will be inert")
            self.pipewire = None
        deck = DeckHandle(serial=self.cfg.serial)
        deck.set_brightness(self.cfg.brightness)
        deck.set_key_callback(self._on_key)
        self.deck = deck
        self._build_active_page()

        signal.signal(signal.SIGHUP, lambda *_: self.reload())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        log.info("running. Ctrl-C to stop.")
        self._stop.wait()
        self._shutdown()

    def stop(self) -> None:
        self._stop.set()

    def reload(self) -> None:
        with self._reload_lock:
            log.info("reloading config")
            try:
                self._load_config()
                self._build_active_page()
            except Exception:
                log.exception("reload failed")

    def _shutdown(self) -> None:
        log.info("shutting down")
        if self.deck is not None:
            self.deck.close()

    # ─── internals ────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        deck_path = self.config_dir / "deck.toml"
        if not deck_path.exists():
            raise FileNotFoundError(f"missing {deck_path}")
        self.cfg = load_deck_config(deck_path)
        self.pages = load_pages(self.config_dir / "pages")
        self.secrets = load_secrets(self.cfg.secrets_path)
        log.info("loaded %d page(s): %s", len(self.pages), sorted(self.pages))

    def _build_active_page(self) -> None:
        assert self.deck is not None and self.cfg is not None
        deps = make_widget_deps(self.cfg, self.deck.key_size)
        deps.mpris = self.mpris
        deps.pipewire = self.pipewire

        def push(idx: int, image) -> None:
            if self.deck is not None:
                self.deck.set_key_image(idx, image)

        def on_change(page: PageDef) -> None:
            assert self.deck is not None
            self.active = ActivePage(
                page,
                deck_cols=self.deck.cols,
                deck_rows=self.deck.rows,
                deps=deps,
                push=push,
            )
            self._draw_active()

        self.page_stack = PageStack(self.pages, self.cfg, on_change=on_change)

    def _draw_active(self) -> None:
        assert self.deck is not None and self.active is not None
        # Blank everything first so stale keys from a deeper page don't linger.
        for i in range(self.deck.key_count):
            self.deck.set_key_image(i, None)
        for idx, image in self.active.render().items():
            self.deck.set_key_image(idx, image)  # type: ignore[arg-type]

    def _on_key(self, idx: int, pressed: bool) -> None:
        if self.active is None or self.page_stack is None:
            return
        if pressed:
            self.active.handle_press(idx)
        else:
            ctx = ActionContext(page_stack=self.page_stack, secrets=self.secrets)
            self.active.handle_release(idx, ctx)


def main() -> int:
    ap = argparse.ArgumentParser(prog="deckctl")
    ap.add_argument(
        "--config-dir",
        default=os.environ.get(
            "DECKCTL_CONFIG", str(Path("~/.config/deckctl").expanduser())
        ),
        help="config directory (default: ~/.config/deckctl)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # PIL spams per-PNG decoder debug lines; never interesting.
    logging.getLogger("PIL").setLevel(logging.INFO)

    Daemon(Path(args.config_dir)).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
