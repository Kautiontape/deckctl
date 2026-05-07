"""Widget base class and registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

from PIL.Image import Image

from ..config import KeyDef

if TYPE_CHECKING:
    from ..icons import IconResolver
    from ..services.bluez import BluezService
    from ..services.ha import HAService
    from ..services.marks import MarksService
    from ..services.mpris import MprisService
    from ..services.pipewire import PipewireService
    from ..services.producers import Producer
    from ..services.subsonic import SubsonicService
    from ..services.sway import SwayService


@dataclass
class WidgetDeps:
    """Shared services widgets may need at construction time."""
    icons: "IconResolver"
    key_size: tuple[int, int]
    font: str
    mpris: "MprisService | None" = None
    pipewire: "PipewireService | None" = None
    ha: "HAService | None" = None
    marks: "MarksService | None" = None
    bluez: "BluezService | None" = None
    subsonic: "SubsonicService | None" = None
    sway: "SwayService | None" = None
    # Dynamic-list producers, keyed by name (e.g. "audio_sink", "bluez").
    # ActivePage looks them up to expand `type = "dynamic"` keys.
    producers: "dict[str, Producer] | None" = None


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
from . import audio_sink as _audio_sink  # noqa: E402, F401
from . import audio_source as _audio_source  # noqa: E402, F401
from . import bluez as _bluez  # noqa: E402, F401
from . import command as _command  # noqa: E402, F401
from . import ha_action as _ha_action  # noqa: E402, F401
from . import mic_mute as _mic_mute  # noqa: E402, F401
from . import mpris as _mpris  # noqa: E402, F401
from . import mpris_loop as _mpris_loop  # noqa: E402, F401
from . import mpris_shuffle as _mpris_shuffle  # noqa: E402, F401
from . import mpris_star as _mpris_star  # noqa: E402, F401
from . import mpris_title as _mpris_title  # noqa: E402, F401
from . import page as _page  # noqa: E402, F401
from . import sway_mark as _sway_mark  # noqa: E402, F401
from . import sway_mark_new as _sway_mark_new  # noqa: E402, F401
from . import sway_workspace as _sway_workspace  # noqa: E402, F401
from . import volume as _volume  # noqa: E402, F401
from . import weather as _weather  # noqa: E402, F401
from . import stubs as _stubs  # noqa: E402, F401  (registers leftover types)
