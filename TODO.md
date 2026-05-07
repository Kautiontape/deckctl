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

- [x] 1. Daemon skeleton: connect, blank-page render, SIGHUP/SIGTERM, systemd
        unit, udev rule.
- [x] 2. `command` and `page` widgets + page navigation stack. Stub widgets
        registered for later types so example layouts render.
- [x] 3. Scratchpad page generator. `deckctl-gen-scratchpads` reads the same
        INI sway uses and writes `pages/scratchpads.toml`. Workflow: edit
        INI → run generator → SIGHUP daemon.
- [x] 4. `mpris` widget. Track + art + play badge, reactive on D-Bus
        PropertiesChanged. Album art fetched (HTTP supported for Navidrome's
        cover-art URLs) and LRU-cached. Direct D-Bus method calls for
        play/pause, next, prev (no shelling to playerctl). GLib mainloop
        thread runs alongside the deck reader thread.
- [x] 5. `volume` and `mic_mute` widgets. PipewireService runs `pactl
        subscribe` for reactive change events; widgets shell to `wpctl` for
        actions. Volume key labels show current %. **Deferred:**
        `audio_sink` widget — needs the dynamic-list widget mechanism;
        easier once the audio-out sub-page exists.
- [x] 6. Weather widget. Open-Meteo API (no key), polls every
        `refresh_minutes` (default 15) on a daemon thread, maps WMO codes
        to FontAwesome cloud/sun/etc. icons. **Deferred:** BlueZ widget
        (same dynamic-list need as audio_sink).
- [x] 7. `ha_action` widget. Calls REST `/api/services/<domain>/<service>`
        with optional entity_id and data. Secrets read from
        `~/.config/deckctl/secrets.env` (HA_URL, HA_TOKEN; gitignored,
        mode 0600). Daemon logs and no-ops if secrets are absent.

## Beyond the build sequence

Things added on top of #1-#7 that are also live:

- [x] Sway marks page with 12 deck slots, assign mode, and bury toggle
      (tap a marked window to send it to scratchpad / bring it back).
- [x] Concurrency: HID writes serialized through DeckHandle._io_lock so
      two reactive services can't interleave image chunks on the wire.
- [x] Page transitions dispose the previous ActivePage so widgets
      unsubscribe from services and weather threads stop.

## Next architectural work

- [ ] **Dynamic-list widget mechanism.** One TOML key expands into N
      runtime keys based on system state, so a widget can fill a region.
      Needed by `audio_sink` and `bluez`. Likely shape: a `dynamic` key
      with `producer = "audio_sink"`, `region = [start_pos, slots]`, and
      the page renderer expands the slots when state changes.
- [ ] **`audio_sink` widget.** Once the dynamic-list lands. One button
      per PipeWire sink with the current default highlighted. Wires the
      "Out" key on Main to the audio-out sub-page.
- [ ] **`bluez` widget.** Same shape as audio_sink but over BlueZ D-Bus.
      Wires the "BT" key on Main.

## Polish / nice-to-haves

- [ ] Marks page: subscribe to sway window-close events to auto-clear
      stale slots instead of pruning lazily on activate.
- [ ] Long-press progress ring rendering (for power-page guards).
- [ ] Auto-dim deck after N seconds idle, wake on key press.
- [ ] Per-page brightness override.
- [ ] State badges on `page` keys (e.g. red dot if a sub-page has an "alarm" state).
- [ ] Multi-deck support (currently first MK.2 wins).
- [ ] Hot-reload of icon theme.

## Smoke testing

- `python3 scripts/smoke_test.py` regenerates `/tmp/deckctl-smoke/*.png`
  for the bundled example pages without touching the deck.

## Known gaps

- Old `~/.dotfiles/streamdeck/streamdeck.conflink/` Python sidecars are kept
  for reference but are Xlib-based and won't run on Wayland. Migrate any
  useful logic (especially `spotify_tracker.py`'s MPRIS art rendering) into
  `deckctl/widgets/mpris.py` then leave the originals as historical archive.
- HA bearer token currently lives in a private dotfiles git history. Rotate
  later; not urgent because repo is private.
