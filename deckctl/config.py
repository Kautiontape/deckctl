"""Config loading. TOML in, dataclasses out."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DeckConfig:
    serial: str | None = None
    brightness: int = 75
    default_page: str = "main"
    font: str = "DejaVu Sans"
    # Auto-dim: drop to `idle_dim_brightness` after `idle_dim_seconds` of
    # no key activity. 0 disables. Wakes back to `brightness` on any key.
    idle_dim_seconds: int = 0
    idle_dim_brightness: int = 15
    icon_dirs: list[Path] = field(default_factory=list)
    secrets_path: Path | None = None
    config_dir: Path = field(default_factory=lambda: Path("~/.config/deckctl").expanduser())


@dataclass
class KeyDef:
    pos: tuple[int, int]
    type: str
    settings: dict


@dataclass
class PageDef:
    name: str
    back: str | None
    keys: list[KeyDef]


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def load_deck_config(path: Path) -> DeckConfig:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    deck = data.get("deck", {})
    paths = data.get("paths", {})
    cfg = DeckConfig(
        serial=deck.get("serial"),
        brightness=int(deck.get("brightness", 75)),
        default_page=deck.get("default_page", "main"),
        font=deck.get("font", "DejaVu Sans"),
        idle_dim_seconds=int(deck.get("idle_dim_seconds", 0)),
        idle_dim_brightness=int(deck.get("idle_dim_brightness", 15)),
        icon_dirs=[_expand(p) for p in paths.get("icons", [])],
        secrets_path=_expand(paths["secrets"]) if "secrets" in paths else None,
        config_dir=path.parent,
    )
    return cfg


def load_page(path: Path) -> PageDef:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    page_meta = data.get("page", {})
    name = page_meta.get("name") or path.stem
    back = page_meta.get("back")

    keys: list[KeyDef] = []
    for raw in data.get("keys", []):
        pos = tuple(raw.pop("pos"))
        if len(pos) != 2:
            raise ValueError(f"{path}: key 'pos' must be [col, row]; got {pos}")
        type_ = raw.pop("type")
        keys.append(KeyDef(pos=pos, type=type_, settings=raw))

    return PageDef(name=name, back=back, keys=keys)


def load_pages(pages_dir: Path) -> dict[str, PageDef]:
    pages: dict[str, PageDef] = {}
    for entry in sorted(pages_dir.iterdir()):
        if entry.suffix != ".toml":
            continue
        page = load_page(entry)
        if page.name in pages:
            raise ValueError(f"duplicate page name {page.name!r} in {entry}")
        pages[page.name] = page
    return pages


def load_secrets(path: Path | None) -> dict[str, str]:
    """Read a `KEY=value` env file. Missing file is fine — returns {}."""
    if path is None or not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out
