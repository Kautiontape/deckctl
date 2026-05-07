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
from .services.bluez import BluezService
from .services.ha import HAService
from .services.marks import MarksService
from .services.mpris import MprisService, start_glib_loop
from .services.pipewire import PipewireService
from .services.producers import AudioSinkProducer, BluezProducer
from .services.subsonic import SubsonicService
from .services.sway import SwayService

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
        self.ha: HAService | None = None
        self.sway: SwayService | None = None
        self.marks: MarksService | None = None
        self.bluez: BluezService | None = None
        self.subsonic: SubsonicService | None = None
        self._stop = threading.Event()
        self._reload_lock = threading.Lock()
        # Idle-dim state.
        self._last_activity = 0.0
        self._dimmed = False
        self._dimmer_thread: threading.Thread | None = None

    # ─── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        import time
        self._load_config()
        assert self.cfg is not None
        self._last_activity = time.monotonic()
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
        self.ha = HAService(
            url=self.secrets.get("HA_URL"),
            token=self.secrets.get("HA_TOKEN"),
        )
        if not self.ha.configured:
            log.info("ha: secrets not set; ha_action keys will be no-ops")
        self.sway = SwayService()
        self.marks = MarksService(self.sway)
        try:
            self.bluez = BluezService()
        except Exception:
            log.exception("bluez init failed; bluetooth widgets will be inert")
            self.bluez = None
        self.subsonic = SubsonicService(
            url=self.secrets.get("SUBSONIC_URL"),
            credential=self.secrets.get("SUBSONIC_CRED"),
        )
        if not self.subsonic.configured:
            log.info(
                "subsonic: no credentials in secrets.env and Feishin storage "
                "didn't yield any either; star button will be inert",
            )
        deck = DeckHandle(serial=self.cfg.serial)
        deck.set_brightness(self.cfg.brightness)
        deck.set_key_callback(self._on_key)
        self.deck = deck
        self._build_active_page()

        signal.signal(signal.SIGHUP, lambda *_: self.reload())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())

        # Auto-dim watcher (only spawned if enabled).
        if self.cfg.idle_dim_seconds > 0:
            self._dimmer_thread = threading.Thread(
                target=self._dim_loop, name="idle-dimmer", daemon=True,
            )
            self._dimmer_thread.start()

        log.info("running. Ctrl-C to stop.")
        self._stop.wait()
        self._shutdown()

    def _dim_loop(self) -> None:
        """Drop brightness when idle for `idle_dim_seconds`. Wakes on key press."""
        import time
        assert self.cfg is not None
        idle_threshold = self.cfg.idle_dim_seconds
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._last_activity
            if not self._dimmed and elapsed >= idle_threshold:
                if self.deck is not None:
                    try:
                        self.deck.set_brightness(self.cfg.idle_dim_brightness)
                        self._dimmed = True
                    except Exception:
                        log.exception("idle dim failed")
            # Poll roughly once a second; not worth the precision of a timer.
            self._stop.wait(1.0)

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
        if self.active is not None:
            self.active.dispose()
            self.active = None
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
        deps.ha = self.ha
        deps.marks = self.marks
        deps.bluez = self.bluez
        deps.subsonic = self.subsonic
        producers: dict[str, object] = {}
        if self.pipewire is not None:
            producers["audio_sink"] = AudioSinkProducer(self.pipewire)
        if self.bluez is not None:
            producers["bluez"] = BluezProducer(self.bluez)
        deps.producers = producers  # type: ignore[assignment]

        def push(idx: int, image) -> None:
            if self.deck is not None:
                self.deck.set_key_image(idx, image)

        def on_change(page: PageDef) -> None:
            assert self.deck is not None
            # Tear down the previous page so its widgets unsubscribe from
            # services. Without this, an old MprisWidget would keep pushing
            # album art to its old key index even after we navigate away.
            if self.active is not None:
                self.active.dispose()
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
        import time
        self._last_activity = time.monotonic()
        # Wake from idle-dim before processing the press, so users see
        # full brightness for the action they're doing.
        if self._dimmed and self.deck is not None and self.cfg is not None:
            try:
                self.deck.set_brightness(self.cfg.brightness)
                self._dimmed = False
            except Exception:
                log.exception("wake brightness restore failed")
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
