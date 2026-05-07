"""Resolve icon names from configured icon directories.

Builds a flat name→path index lazily on first lookup. Supports SVG via
cairosvg and PNG/JPEG natively.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)


class IconResolver:
    def __init__(self, search_dirs: list[Path]):
        self.search_dirs = [Path(d) for d in search_dirs if Path(d).exists()]
        self._index: dict[str, Path] | None = None
        self._cache: dict[tuple[str, int], Image.Image] = {}

    def _build_index(self) -> dict[str, Path]:
        index: dict[str, Path] = {}
        for root in self.search_dirs:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg"}:
                    continue
                name = path.stem
                # First match wins so explicit dirs (listed earlier) take
                # precedence over fallback theme dirs.
                index.setdefault(name, path)
        log.debug("icon index built: %d entries", len(index))
        return index

    def resolve(self, name: str | None) -> Path | None:
        if not name:
            return None
        # Absolute or ~ paths are passed through unmodified.
        if name.startswith("/") or name.startswith("~"):
            p = Path(name).expanduser()
            return p if p.exists() else None
        if self._index is None:
            self._index = self._build_index()
        return self._index.get(name)

    def load(self, name: str | None, size: int = 72) -> Image.Image | None:
        if not name:
            return None
        cache_key = (name, size)
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = self.resolve(name)
        if path is None:
            log.warning("icon not found: %r", name)
            return None

        try:
            if path.suffix.lower() == ".svg":
                import cairosvg

                png_bytes = cairosvg.svg2png(
                    bytestring=path.read_bytes(),
                    output_width=size,
                    output_height=size,
                )
                if not png_bytes:
                    return None
                img = Image.open(BytesIO(png_bytes)).convert("RGBA")
            else:
                img = Image.open(path).convert("RGBA")
                if img.size != (size, size):
                    img = img.resize((size, size), Image.Resampling.LANCZOS)
        except Exception:
            log.exception("icon load failed: %s", path)
            return None

        self._cache[cache_key] = img
        return img
