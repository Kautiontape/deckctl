# deckctl

A small Python daemon that drives an Elgato Stream Deck on Linux/Wayland (Sway).
Replaces the previous StreamController + streamdeck-ui setups with something
hand-editable, dotfiles-friendly, and reactive (no polling for things that emit
D-Bus events).

Designed for an **Elgato Stream Deck MK.2** (5×3, 15 keys, USB ID `0fd9:0080`).
Other models will probably work but layouts assume 15 keys.

## Status

Pre-alpha. See `TODO.md` for what is and isn't built.

## Layout

- `deckctl/` — Python package (daemon entrypoint + widgets)
- `config/` — example TOML configs; the live versions live in `~/.config/deckctl/`
  (symlinked from `~/.dotfiles/streamdeck/`)
- `systemd/` — user service unit
- `udev/` — udev rule giving the user access to the device hidraw node
- `scripts/` — generators (e.g. scratchpads page from sway INI)

See `ARCHITECTURE.md` for the design in detail.

## Install (planned)

```sh
pip install --user -e .
sudo cp udev/99-streamdeck-mk2.rules /etc/udev/rules.d/ && sudo udevadm control --reload
ln -s "$PWD/systemd/deckctl.service" ~/.config/systemd/user/
ln -s "$PWD/config" ~/.config/deckctl    # or use the dotfiles symlink
systemctl --user enable --now deckctl
```

## Related repos

- **Config lives in dotfiles**: `~/.dotfiles/streamdeck/`
- **Old setups** (kept around, inactive): `~/.dotfiles/streamdeck/streamdeck.conflink/`
  (xmonad-era live tiles + spotify tracker, broken on Wayland) and
  `streamdeck_ui.json.symlink` (streamdeck-ui JSON config).

## License

MIT (intent — not yet committed).
