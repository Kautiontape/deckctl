# deckctl architecture

## Goals

- Hand-editable TOML config in dotfiles, single source of truth
- Reactive: D-Bus subscriptions for MPRIS/BlueZ/PipeWire; poll only what must
  be polled (weather, time)
- Sway/Wayland-native (no Xlib)
- Secrets live outside dotfiles (`~/.config/deckctl/secrets.env`, mode 0600)
- One daemon, one process, started by systemd user service on udev plug

## Hardware

Elgato Stream Deck MK.2, USB `0fd9:0080`. 5 columns × 3 rows, 15 keys.
Key positions are addressed as `(col, row)` with `(0, 0)` top-left.

## Process model

```
┌──────────────────────────────────────────────────────────────────┐
│ deckctl daemon                                                   │
│                                                                  │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐        │
│  │ Config      │──▶│ PageStack    │──▶│ ActiveRenderer  │        │
│  │ loader      │   │ (push/pop)   │   │ (per-key state) │        │
│  └─────────────┘   └──────────────┘   └─────────────────┘        │
│         ▲                  ▲                   │                 │
│         │ SIGHUP           │ key events        ▼                 │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐        │
│  │ inotify on  │   │ DeckDevice   │◀──│ FrameComposer   │        │
│  │ ~/.config/  │   │ (hidapi)     │   │ (PIL)           │        │
│  └─────────────┘   └──────────────┘   └─────────────────┘        │
│                                                                  │
│  ┌─ Reactive sources (asyncio tasks) ──────────────────────────┐ │
│  │ MPRIS (D-Bus)  PipeWire  BlueZ  weather  HA REST  scheduler │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

The `python-elgato-streamdeck` library provides HID I/O; we drive it through
its `StreamDeck.set_key_callback()` for input and `set_key_image()` for output.

The current implementation is **threaded**, not asyncio: the StreamDeck
library's reader runs on a worker thread and invokes our key callback there.
We'll introduce `asyncio` only when reactive widgets land (MPRIS, BlueZ,
PipeWire) — at that point each subscription becomes its own task and posts
invalidations back to the main thread via a thread-safe queue.

## Config language (TOML)

### Root: `~/.config/deckctl/deck.toml`

```toml
[deck]
# Optional. If unset, first detected MK.2 wins.
serial = "DL26L2A88614"
brightness = 75            # 0-100
default_page = "main"
font = "DejaVu Sans"

[paths]
icons = ["~/.config/deckctl/icons", "/usr/share/icons/Papirus-Dark/24x24"]
secrets = "~/.config/deckctl/secrets.env"

[reload]
# Watch these dirs; SIGHUP also forces reload
watch = ["~/.config/deckctl/pages", "~/.config/deckctl/deck.toml"]
```

### Pages: `~/.config/deckctl/pages/<name>.toml`

```toml
[page]
name = "main"
back = "main"               # where `back` action returns; only for sub-pages

[[keys]]
pos = [0, 0]
type = "weather"
location = "39.122318,-76.561760"
unit = "F"
refresh_minutes = 15

[[keys]]
pos = [1, 0]
type = "mpris"
player = "Feishin"          # falls back to active MPRIS if not running
on_press = "playerctl --player=Feishin play-pause"
on_long_press = "page:feishin"

[[keys]]
pos = [3, 2]
type = "page"
target = "ha"
icon = "preferences-system"
label = "Home"
```

## Widget catalog

| Widget       | Purpose                                  | Reactive source       |
|--------------|------------------------------------------|-----------------------|
| `command`    | Static label/icon, runs shell on press   | none                  |
| `page`       | Navigation, optional state badge         | child page state      |
| `mpris`      | Track + art + play state                 | D-Bus PropertiesChanged |
| `weather`    | Temp + condition                         | poll (15 min)         |
| `volume`     | Adjust default sink, show %              | PipeWire events       |
| `mic_mute`   | Toggle mic, icon reflects state          | PipeWire events       |
| `audio_sink` | One button per sink, current highlighted | PipeWire events       |
| `bluez`      | One button per paired device             | BlueZ D-Bus           |
| `ha_action`  | HA REST call, optional state read        | HA SSE (later)        |
| `clock`      | Time display                             | timer                 |

## Action vocabulary

A key's `on_press` / `on_long_press` accept these forms:

| Form                     | Effect                                       |
|--------------------------|----------------------------------------------|
| `command:<shell>`        | `sh -c <shell>`, fork+exec, never blocks     |
| `<shell>` (no prefix)    | Same as `command:` — bare strings shell out  |
| `page:<name>`            | Push page onto navigation stack              |
| `back`                   | Pop page stack; falls back to default_page   |
| `dbus:<bus>:<path>:<method>` | Direct D-Bus method call                |
| `ha:<entity>:<service>`  | HA service call (uses secrets file)          |

Long press = ≥ 800 ms by default; configurable per-key with `long_press_ms`.

## Pages (proposed)

### Main

```
┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ Weather │ Now     │ Prev    │ Next    │ Mic     │
│  72°F   │ Playing │         │         │ Mute    │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ Audio   │ Vol -   │ Sys     │ Vol +   │ BT      │
│ Out →   │         │ Mute    │         │ →       │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ Lock    │ Scratch │ Sway    │ HA      │ Power   │
│         │ →       │ →       │ →       │ →       │
└─────────┴─────────┴─────────┴─────────┴─────────┘
```

### Feishin

```
┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ ← Back  │ Album   │ Loop    │ Shuffle │ Play-   │
│         │ Art     │         │         │ lists → │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ Prev    │ Play /  │ Next    │ Mic     │ Open    │
│         │ Pause   │         │ Mute    │ Feishin │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ Mute    │ Vol -   │ Track   │ Vol +   │ Like /  │
│         │         │ Title   │         │ Star    │
└─────────┴─────────┴─────────┴─────────┴─────────┘
```

### Scratchpads (auto-generated from `~/.config/sway/scratchpad-config.ini`)

The same INI that drives sway's launch mode also drives this page via
`scripts/gen-scratchpads-page.py`. Re-run the generator after editing the INI.

### Sway (window management)

```
┌─────────┬─────────┬─────────┬─────────┬─────────┐
│ ← Back  │ Tabbed  │ Stacked │ Split H │ Split V │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ Float   │ Full-   │ Pull    │ Mark    │ Resize  │
│ Toggle  │ screen  │ Window  │ Window  │ Mode    │
├─────────┼─────────┼─────────┼─────────┼─────────┤
│ →WS1    │ →WS2    │ →WS3    │ →WS4    │ Reload  │
└─────────┴─────────┴─────────┴─────────┴─────────┘
```

### Audio Out, Bluetooth (dynamic)

These pages are mostly empty in TOML — the framework has `dynamic_list` keys
that materialize one button per sink/device at runtime. The TOML defines:
back button, fixed slots (e.g. "scan", "power"), and where the dynamic list
should land in the grid.

### HA

Buttons are hand-defined in `pages/ha.toml`. Each button supports either a
one-shot service call or a two-state toggle (queries entity, flips icon).
Token comes from `secrets.env`. **Never commit secrets.**

Confirmed Main-page HA targets:
- `script.toggle_mute_office_speaker` — service call to mute/unmute the office speaker
- `media_player.britney_speaker` — HA's name for the office speaker (legacy);
  use `media_player/volume_up` and `media_player/volume_down` for ±

### Power

Lock / Suspend / Logout / Reboot / Shutdown.
Reboot/Shutdown require **press-and-hold ≥ 1s** to fire, with a visible
progress ring on the key. Lock and Suspend fire on tap.

## Secrets

`~/.config/deckctl/secrets.env` (chmod 600, gitignored, **not** in dotfiles):

```sh
HA_URL=http://192.168.1.101:8123
HA_TOKEN=<long-lived access token>
```

Action handlers source this when they need it. The `ha_action` widget reads
it once at daemon start and on SIGHUP.

## Lifecycle & reload

- Daemon launched by systemd user service `deckctl.service`
- Service starts on user login OR on udev plug event
  (rule: `udev/99-streamdeck-mk2.rules`)
- `SIGHUP` → re-read all config without restart
- `SIGTERM` → blank deck, release device, exit cleanly
- Config dir watched via `inotify` for auto-reload (best-effort; SIGHUP is the
  guaranteed path)

## Open design questions

See `TODO.md` for the canonical list. The biggest one: **how to drive Feishin
playlist selection** — likely Subsonic API on the backing server, but needs
research before committing to an interface.
