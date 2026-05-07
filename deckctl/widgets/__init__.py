"""Widget base class and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from PIL.Image import Image

from ..config import KeyDef


@dataclass
class WidgetDeps:
    """Shared services widgets may need at construction time."""
    icons: object  # IconResolver — typed as object to avoid circular import games
    key_size: tuple[int, int]
    font: str


class Widget(Protocol):
    """Minimal interface every widget implements."""

    def render(self) -> Image: ...
    def on_press(self, ctx) -> None: ...
    def on_long_press(self, ctx) -> None: ...

    # Optional: widgets may set this to be called when their visible state
    # changes (e.g. mpris track changes). The page renderer assigns it.
    invalidate: Callable[[], None] | None


_REGISTRY: dict[str, type] = {}


def register(name: str):
    def deco(cls):
        _REGISTRY[name] = cls
        return cls
    return deco


def build(key: KeyDef, deps: WidgetDeps) -> Widget:
    cls = _REGISTRY.get(key.type)
    if cls is None:
        raise ValueError(
            f"unknown widget type {key.type!r}; known: {sorted(_REGISTRY)}"
        )
    return cls(key.settings, deps)


# Import widget modules so their @register calls take effect.
from . import command as _command  # noqa: E402, F401
from . import page as _page  # noqa: E402, F401
from . import stubs as _stubs  # noqa: E402, F401
