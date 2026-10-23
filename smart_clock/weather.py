"""Optional outdoor temperature from Open-Meteo (free, no API key)."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Optional

log = logging.getLogger(__name__)

API = "https://api.open-meteo.com/v1/forecast"
REFRESH_SECONDS = 15 * 60
STALE_SECONDS = 2 * 60 * 60


def fetch_temperature(latitude: float, longitude: float, unit: str) -> float:
    query = urllib.parse.urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m",
        "temperature_unit": unit,
    })
    with urllib.request.urlopen(f"{API}?{query}", timeout=10) as response:
        payload = json.load(response)
    return float(payload["current"]["temperature_2m"])


class Weather:
    """Keeps the latest temperature fresh from a background thread."""

    def __init__(self, latitude: float, longitude: float, unit: str = "celsius",
                 fetch: Callable[[float, float, str], float] = fetch_temperature) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.unit = unit
        self._fetch = fetch
        self._value: Optional[float] = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="weather", daemon=True).start()

    def refresh(self) -> None:
        try:
            value = self._fetch(self.latitude, self.longitude, self.unit)
        except Exception as exc:  # network down, bad reply: keep the old value
            log.warning("weather update failed: %s", exc)
            return
        with self._lock:
            self._value = value
            self._fetched_at = time.monotonic()

    def temperature(self) -> Optional[float]:
        with self._lock:
            if self._value is None or time.monotonic() - self._fetched_at > STALE_SECONDS:
                return None
            return self._value

    def text(self) -> Optional[str]:
        """Something like "23.5°C", or None when there is no fresh reading."""
        value = self.temperature()
        if value is None:
            return None
        return f"{value:.1f}°{'F' if self.unit == 'fahrenheit' else 'C'}"

    def _loop(self) -> None:
        while True:
            self.refresh()
            time.sleep(REFRESH_SECONDS)
