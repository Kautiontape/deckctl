"""`weather` widget — current temperature + condition from Open-Meteo."""

from __future__ import annotations

import json
import logging
import threading
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL.Image import Image

from ..render import render_key
from . import WidgetDeps, register

log = logging.getLogger(__name__)

# WMO weather codes → FontAwesome icon name. Coarse but readable.
# https://open-meteo.com/en/docs#weather_variable_documentation
_WMO_ICON: dict[int, str] = {
    0: "sun",
    1: "cloud", 2: "cloud", 3: "cloud",
    45: "smog", 48: "smog",
    51: "cloud-rain", 53: "cloud-rain", 55: "cloud-rain",
    56: "cloud-rain", 57: "cloud-rain",
    61: "cloud-rain", 63: "cloud-rain", 65: "cloud-rain",
    66: "cloud-rain", 67: "cloud-rain",
    71: "snowflake", 73: "snowflake", 75: "snowflake", 77: "snowflake",
    80: "cloud-showers-heavy", 81: "cloud-showers-heavy", 82: "cloud-showers-heavy",
    85: "snowflake", 86: "snowflake",
    95: "cloud-bolt", 96: "cloud-bolt", 99: "cloud-bolt",
}


@register("weather")
class WeatherWidget:
    """Settings:

        location          "lat,lon"
        unit              "F" (default) or "C"
        refresh_minutes   default 15
    """

    def __init__(self, settings: dict, deps: WidgetDeps):
        self._deps = deps
        self.invalidate = None

        loc = settings.get("location", "")
        try:
            lat, lon = loc.split(",")
            self.lat = float(lat.strip())
            self.lon = float(lon.strip())
        except ValueError:
            log.warning("weather: bad location %r; expected 'lat,lon'", loc)
            self.lat = self.lon = 0.0

        unit = (settings.get("unit") or "F").upper()
        self.unit = "F" if unit.startswith("F") else "C"
        self.refresh_seconds = int(settings.get("refresh_minutes", 15)) * 60

        self._state: tuple[float, int] | None = None  # (temp, wmo_code)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._poll_loop, name="weather", daemon=True,
        )
        self._thread.start()

    # ─── render ───────────────────────────────────────────────────────────

    def render(self) -> Image:
        if self._state is None:
            return render_key(
                size=self._deps.key_size,
                icons=self._deps.icons,  # type: ignore[arg-type]
                icon="sun",
                label="…",
                font_family=self._deps.font,
                bg=(20, 20, 20), fg=(180, 180, 180),
            )
        temp, code = self._state
        return render_key(
            size=self._deps.key_size,
            icons=self._deps.icons,  # type: ignore[arg-type]
            icon=_WMO_ICON.get(code, "cloud"),
            label=f"{round(temp)}°{self.unit}",
            font_family=self._deps.font,
        )

    # ─── actions ──────────────────────────────────────────────────────────

    def on_press(self, ctx) -> None:
        # Tap forces an immediate refresh.
        threading.Thread(target=self._fetch_once, daemon=True).start()

    def on_long_press(self, ctx) -> None:
        self.on_press(ctx)

    # ─── polling ──────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._fetch_once()
            self._stop.wait(self.refresh_seconds)

    def _fetch_once(self) -> None:
        unit = "fahrenheit" if self.unit == "F" else "celsius"
        params = {
            "latitude": f"{self.lat}",
            "longitude": f"{self.lon}",
            "current": "temperature_2m,weather_code",
            "temperature_unit": unit,
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
        try:
            req = Request(url, headers={"User-Agent": "deckctl/0.0"})
            with urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
        except (URLError, ValueError, TimeoutError):
            log.exception("weather: fetch failed")
            return

        cur = data.get("current") or {}
        try:
            temp = float(cur["temperature_2m"])
            code = int(cur["weather_code"])
        except (KeyError, TypeError, ValueError):
            log.warning("weather: malformed response %r", data)
            return

        new_state = (temp, code)
        if new_state == self._state:
            return
        self._state = new_state
        cb = self.invalidate
        if cb is not None:
            cb()
