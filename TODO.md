# deckctl TODO

Tracking research, deferred work, and known gaps. Not exhaustive — just the
things we explicitly chose to defer or aren't sure about yet.

## Research

- [ ] **Feishin playlist control.** No clear MPRIS path. Candidates:
      - Subsonic API on backing server (probably Navidrome). Cleanest if available.
      - Feishin CLI args / URI scheme — does it accept `feishin://playlist/<id>`?
      - Simulated keystrokes via `wtype` (ugly, fragile).
      Until decided, the Playlists sub-page is a placeholder.
- [ ] **Feishin "favorite/star" support.** Subsonic API has a `star` endpoint;
      check if it's wired through Feishin's MPRIS or if we hit Subsonic directly.
- [ ] **Feishin shuffle/loop via D-Bus.** MPRIS has `Shuffle` and `LoopStatus`
      properties — verify Feishin honors writes to them.
- [ ] **HA Server-Sent Events** for state subscriptions instead of polling
      after a button press. Nice-to-have once basic HA actions work.

## Build sequence

Numbers map to the build sequence in the design proposal.

- [ ] 1. Daemon skeleton: connect, blank-page render, SIGHUP/SIGTERM, systemd
        unit, udev rule.
- [ ] 2. `command` and `page` widgets + page navigation stack.
- [ ] 3. Scratchpad page generator from `~/.config/sway/scratchpad-config.ini`.
- [ ] 4. `mpris` widget: track text + album art + play/pause. Feishin page.
- [ ] 5. `volume`, `mic_mute`, `audio_sink` widgets (PipeWire).
- [ ] 6. Weather, BlueZ, Sway, Power pages.
- [ ] 7. HA actions + secrets handling.

## Polish / nice-to-haves

- [ ] Long-press progress ring rendering (for power-page guards).
- [ ] Auto-dim deck after N seconds idle, wake on key press.
- [ ] Per-page brightness override.
- [ ] State badges on `page` keys (e.g. red dot if a sub-page has an "alarm" state).
- [ ] Multi-deck support (currently first MK.2 wins).
- [ ] Hot-reload of icon theme.

## Known gaps

- Old `~/.dotfiles/streamdeck/streamdeck.conflink/` Python sidecars are kept
  for reference but are Xlib-based and won't run on Wayland. Migrate any
  useful logic (especially `spotify_tracker.py`'s MPRIS art rendering) into
  `deckctl/widgets/mpris.py` then leave the originals as historical archive.
- HA bearer token currently lives in a private dotfiles git history. Rotate
  later; not urgent because repo is private.
