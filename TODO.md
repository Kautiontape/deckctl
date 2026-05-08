# deckctl TODO

Tracking research, deferred work, and known gaps. Not exhaustive — just the
things we explicitly chose to defer or aren't sure about yet.

## Research

- [x] **Feishin shuffle/loop via D-Bus.** Confirmed: Feishin exposes both
      Shuffle (b, readwrite) and LoopStatus (s, readwrite) on
      org.mpris.MediaPlayer2.Player. Reactive widgets `mpris_shuffle` and
      `mpris_loop` read state via PropertiesChanged and write on press.
- [x] **Feishin star support.** No MPRIS path. Goes via Subsonic API on
      the backing Navidrome (`/rest/star` and `/rest/unstar` with the
      Subsonic auth-by-token credential). Credentials auto-extracted from
      Feishin's IndexedDB / LocalStorage leveldb files; can be overridden
      via SUBSONIC_URL + SUBSONIC_CRED in secrets.env.
- [ ] **Feishin playlist control.** No MPRIS Playlists interface
      (verified: `HasTrackList = false`, no `org.mpris.MediaPlayer2.Playlists`
      interface in Feishin's introspection). The Subsonic API has
      `getPlaylists` for listing and `getPlaylist?id=…` for tracks but
      can't directly tell Feishin to *play* a playlist. Possible paths:
      - `savePlayQueue` to push a queue server-side; Feishin would need
        to pick that up via `getPlayQueue`. The `serverPlayQueue` feature
        flag is in Feishin's saved server features list — worth probing.
      - Feishin URL scheme (`feishin://`) — needs to be checked; the
        `OpenUri` MPRIS method exists but isn't documented for Feishin.
      Until decided, the Playlists sub-page is still a placeholder.
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

- [x] **Dynamic-list widget mechanism.** A `[[keys]]` entry with
      `type = "dynamic"`, `producer = "<name>"`, `slots = N` is expanded
      by ActivePage into N regular widgets at sequential positions
      starting from `pos`. Each `_DynamicRegion` subscribes to its
      producer and rebuilds in place on state changes.
- [x] **`audio_sink` widget + audio-out page.** Sinks listed by
      `AudioSinkProducer` (wraps PipewireService); current default
      flagged with a green top border. Tap to switch. Reactive on
      pactl subscribe events.
- [x] **`bluez` widget.** Lists paired devices via BlueZ ObjectManager
      (system bus). Connected devices flagged with a blue top border;
      tap toggles connect/disconnect. Reactive on Device1
      PropertiesChanged + InterfacesAdded/Removed signals. Icons come
      from BlueZ's `Icon` property (audio-headset, phone, etc.) which
      maps directly to Papirus device icons.

## Polish / nice-to-haves

Done:

- [x] Marks page: subscribe to sway window-close events to auto-clear
      stale slots instead of pruning lazily on activate.
- [x] Long-press progress ring rendering. Opt-in via `long_press_ms` or
      `on_long_press` in the key's TOML.
- [x] Auto-dim deck after `idle_dim_seconds` of inactivity, wake on key
      press. SIGHUP-toggleable; brightness restored before action runs.

Skipped (per user):

- [ ] ~~Per-page brightness override~~ — not useful enough.
- [ ] ~~Multi-deck support~~ — only one deck.

Done since last:

- [x] **Sway workspace indicator** on the Sway page. WS keys are now
      `sway_workspace` widgets that highlight live as you switch
      workspaces.
- [x] **Audio input picker.** Mic long-press → audio-in page mirroring
      audio-out.
- [x] **Disconnect watchdog.** DeckHandle.connected flips on HID error;
      the deck-watchdog thread tries 3 reconnects and falls through to
      a non-zero exit so systemd can restart us cleanly.
- [~] **Recents row** built (RecentsService + RecentsProducer +
      sway_window widget) but pulled from Main: focus_con's
      "move to current workspace + float-enable" was disruptive across
      tilings. Code stays in tree for a future revisit with a less
      aggressive activation pattern (just `swaymsg workspace number N`
      then focus, no move/float).

Open / speculative:

- [ ] **HA toggle widget + SSE.** Deck buttons that control an HA entity
      AND reflect its state (e.g. office light shows on/off). Needs:
      (1) ha_toggle widget reading state, rendering icon per state,
      tapping calls toggle service; (2) HAService.subscribe via SSE
      `/api/stream` so the button updates when changed elsewhere.
      Highest-value remaining item — your HA has 23 lights + 52
      switches.
- [ ] State badges on `page` keys. e.g. BT button shows "2" when 2
      devices are connected, marks button shows count of filled slots.
      Concrete use cases: BT count, marks count, audio-out current sink
      name. Worth doing once we know which feel useful.
- [ ] `dbus:` action prefix. We shell to `dbus-send` for the Open
      Feishin button. A native `dbus:bus:path:method` action prefix
      would be cleaner.
- [ ] Hot-reload of icon theme. Low value.
- [ ] Recents backfill from sway tree at daemon start (only relevant
      if the recents row comes back).

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
