"""Tests for WeatherService: cache hit, stale-cache fallback, geocoding miss."""
import httpx
import pytest

from app.models import Weather
from app.services.weather import WeatherService, WeatherUnavailable


class MockTransport(httpx.MockTransport):
    """Route requests to canned handlers by URL substring."""


def weather_client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0)
    )


def geo_and_forecast_ok(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "geocoding" in url:
        return httpx.Response(
            200,
            json={"results": [{"name": "Paris", "latitude": 48.85, "longitude": 2.35}]},
        )
    if "forecast" in url:
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 20.0,
                    "apparent_temperature": 21.0,
                    "precipitation": 0.0,
                    "weather_code": 0,
                    "wind_speed_10m": 5.0,
                }
            },
        )
    return httpx.Response(404)


def test_fetch_parses_open_meteo_response():
    svc = WeatherService(client=weather_client(geo_and_forecast_ok))
    w = svc.current("Paris")
    assert w.city == "Paris"
    assert w.temperature_c == 20.0


def test_cache_prevents_second_call():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return geo_and_forecast_ok(request)

    svc = WeatherService(client=weather_client(handler))
    svc.current("Paris")
    svc.current("Paris")
    assert calls["n"] == 2  # one geocode + one forecast, then cached


def test_stale_cache_served_on_network_failure():
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            raise httpx.ConnectError("network down")
        return geo_and_forecast_ok(request)

    svc = WeatherService(client=weather_client(handler))
    first = svc.current("Paris")
    state["fail"] = True
    second = svc.current("Paris")
    assert second == first  # stale value, not an error


def test_no_cache_and_failure_raises():
    def handler(request):
        raise httpx.ConnectError("network down")

    svc = WeatherService(client=weather_client(handler))
    with pytest.raises(WeatherUnavailable):
        svc.current("Paris")


def test_unknown_city_raises():
    def handler(request):
        if "geocoding" in url_of(request):
            return httpx.Response(200, json={"results": []})
        return geo_and_forecast_ok(request)

    def url_of(request):
        return str(request.url)

    svc = WeatherService(client=weather_client(handler))
    with pytest.raises(WeatherUnavailable):
        svc.current("Atlantis")
