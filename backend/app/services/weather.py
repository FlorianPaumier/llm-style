"""WeatherService: Open-Meteo (free, no API key) with 30-min cache and fallback.

Two endpoints:
- Geocoding: https://geocoding-api.open-meteo.com/v1/search?name=<city>
- Forecast:  https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..
             &current=temperature_2m,apparent_temperature,precipitation,
                       weather_code,wind_speed_10m
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from ..models import Weather

CACHE_TTL_SECONDS = 30 * 60
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = httpx.Timeout(8.0)


class WeatherUnavailable(Exception):
    """Raised when no current weather can be fetched or recovered from cache."""


class WeatherService:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._cache: dict[str, tuple[float, Weather]] = {}  # city -> (monotonic ts, weather)

    def current(self, city: str) -> Weather:
        """Current weather for a city, served from cache when fresh."""
        now = time.monotonic()
        cached = self._cache.get(city)
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        try:
            weather = self._fetch(city)
        except WeatherUnavailable:
            if cached:
                return cached[1]
            raise
        except Exception as exc:
            # Network/open-meteo failure: serve stale cache rather than failing.
            if cached:
                return cached[1]
            raise WeatherUnavailable(str(exc)) from exc
        self._cache[city] = (now, weather)
        return weather

    def _fetch(self, city: str) -> Weather:
        geo = self._client.get(
            GEO_URL, params={"name": city, "count": 1, "language": "en"}
        )
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            raise WeatherUnavailable(f"Unknown city: {city!r}")
        loc = results[0]

        fc = self._client.get(
            FORECAST_URL,
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
            },
        )
        fc.raise_for_status()
        current = fc.json()["current"]

        return Weather(
            city=loc["name"],
            temperature_c=current["temperature_2m"],
            apparent_temperature_c=current["apparent_temperature"],
            precipitation_mm=current["precipitation"],
            wind_speed_kmh=current["wind_speed_10m"],
            weather_code=current["weather_code"],
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
