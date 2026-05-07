"""Dynamic-list producers.

A producer turns runtime state (PipeWire sinks, BlueZ devices, …) into a
list of items. Each item declares which widget type to instantiate and
the settings to pass it. Pages declare a region of N slots and a
producer; the page expander materializes items[0..N] as real widgets at
sequential positions in the region.

Producers also expose subscribe() so the page can rebuild the region
when state changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .pipewire import PipewireService


@dataclass
class ProducerItem:
    """One item in a dynamic list. Becomes a single widget on the deck."""
    widget_type: str
    settings: dict


class Producer(Protocol):
    def items(self) -> list[ProducerItem]: ...
    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]: ...


class AudioSinkProducer:
    """Lists default-audio sinks with the active one flagged."""

    def __init__(self, pipewire: "PipewireService"):
        self.pipewire = pipewire

    def items(self) -> list[ProducerItem]:
        return [
            ProducerItem(
                widget_type="audio_sink",
                settings={
                    "sink_name": s["name"],
                    "description": s["description"],
                    "is_default": s["default"],
                },
            )
            for s in self.pipewire.audio_sinks()
        ]

    def subscribe(self, cb: Callable[[], None]) -> Callable[[], None]:
        return self.pipewire.subscribe(cb)
