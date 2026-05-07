"""`mpris` widget — track + art + play state, reactive on D-Bus."""

from __future__ import annotations

import logging

from PIL import Image, ImageDraw

from ..actions import execute
from ..render import _font, render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)


@register("mpris")
class MprisWidget:
    """Renders the currently-playing track for one MPRIS player.

    Settings:
        player          short name, e.g. "Feishin"
        size            "normal" (default) — overlays title/artist
                        "large" — full-bleed art, no overlay
        on_press        action override (default: D-Bus PlayPause)
        on_long_press   action override (default: none)
    """

    def __init__(self, settings: dict, deps: WidgetDeps):
        self.player: str = settings.get("player") or "Feishin"
        self.size_mode: str = settings.get("size", "normal")
        self.on_press_action: str | None = settings.get("on_press")
        self.on_long_press_action: str | None = settings.get("on_long_press")
        self._deps = deps
        self.invalidate = None

        if deps.mpris is not None:
            deps.mpris.subscribe(self.player, self._on_change)

    # ─── render ───────────────────────────────────────────────────────────

    def render(self) -> Image.Image:
        w, h = self._deps.key_size
        if self._deps.mpris is None:
            return self._fallback("(no D-Bus)")
        state = self._deps.mpris.state(self.player)
        if state is None:
            return self._fallback(self.player)

        art = self._deps.mpris.art(state["art_url"]) if state.get("art_url") else None

        if art is None:
            return render_key(
                size=(w, h),
                icons=self._deps.icons,  # type: ignore[arg-type]
                icon="music",
                label=state["title"] or self.player,
                font_family=self._deps.font,
            )

        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        # Fit art square to key.
        scaled = art.resize((w, h), Image.Resampling.LANCZOS)
        canvas.paste(scaled.convert("RGB"), (0, 0))

        # Optional overlay: title/artist + play-state badge.
        if self.size_mode != "large":
            self._draw_overlay(canvas, state)

        return canvas

    def _draw_overlay(self, canvas: Image.Image, state: dict) -> None:
        w, h = canvas.size
        d = ImageDraw.Draw(canvas, "RGBA")

        # Bottom strip with semi-transparent background for text.
        strip_h = 18
        d.rectangle(((0, h - strip_h), (w, h)), fill=(0, 0, 0, 180))
        title = state.get("title") or ""
        font = _font(self._deps.font, 10)
        # Truncate to roughly fit; cheap version, not measured per-glyph.
        if len(title) > 12:
            title = title[:11] + "…"
        bbox = d.textbbox((0, 0), title, font=font)
        tw = bbox[2] - bbox[0]
        d.text(((w - tw) // 2, h - strip_h + 3), title, font=font, fill=(255, 255, 255))

        # Play-state badge top-left.
        status = state.get("status", "Stopped")
        badge = "▶" if status == "Playing" else ("⏸" if status == "Paused" else "■")
        # Use a font that has these glyphs; Noto Sans Symbols2 covers them.
        sym = _font("Noto Sans Symbols2", 12)
        d.rectangle(((2, 2), (18, 18)), fill=(0, 0, 0, 180))
        d.text((4, 2), badge, font=sym, fill=(255, 255, 255))

    def _fallback(self, label: str) -> Image.Image:
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon="music",
            label=label,
            font_family=self._deps.font,
            bg=(20, 20, 20),
            fg=(180, 180, 180),
        )

    # ─── actions ──────────────────────────────────────────────────────────

    def on_press(self, ctx) -> None:
        if self.on_press_action:
            execute(self.on_press_action, ctx)
            return
        if self._deps.mpris is not None:
            self._deps.mpris.play_pause(self.player)

    def on_long_press(self, ctx) -> None:
        if self.on_long_press_action:
            execute(self.on_long_press_action, ctx)
            return
        # Default long-press is page:feishin (matches the example layout).
        execute("page:feishin", ctx)

    # ─── reactive ─────────────────────────────────────────────────────────

    def _on_change(self) -> None:
        cb = self.invalidate
        if cb is not None:
            cb()
