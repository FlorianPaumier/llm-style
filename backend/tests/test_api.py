"""API tests via TestClient: CRUD, validation, settings, recommend wiring."""
import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


@pytest.fixture()
def api(tmp_path):
    cfg = AppConfig(db_path=tmp_path / "api.db")
    app = create_app(cfg)
    # `with` runs the lifespan so app.state.weather/recommender exist.
    with TestClient(app) as client:
        yield client, app


ITEM = {
    "name": "Navy tee",
    "type": "top",
    "color": "navy",
    "warmth": 2,
    "formality": 1,
    "style_tags": "minimal",
}


class TestItemsApi:
    def test_crud_roundtrip(self, api):
        client, _ = api
        r = client.post("/api/items", json=ITEM)
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["id"] == 1

        assert client.get("/api/items").json() == [created]

        r = client.put(f"/api/items/{created['id']}", json={**ITEM, "formality": 3})
        assert r.status_code == 200 and r.json()["formality"] == 3

        assert client.delete(f"/api/items/{created['id']}").status_code == 204
        assert client.get("/api/items").json() == []

    def test_validation_rejects_bad_type(self, api):
        client, _ = api
        r = client.post("/api/items", json={**ITEM, "type": "hat"})
        assert r.status_code == 422

    def test_404_on_missing(self, api):
        client, _ = api
        assert client.get("/api/items/42").status_code == 404
        assert client.delete("/api/items/42").status_code == 404


class TestSettingsApi:
    def test_defaults_and_update(self, api):
        client, _ = api
        r = client.get("/api/settings")
        assert r.json() == {
            "city": "Paris",
            "model": "gemma3:12b",
            "ollama_url": "http://localhost:11434",
        }
        r = client.put("/api/settings", json={"city": "Lyon"})
        assert r.json()["city"] == "Lyon"
        assert r.json()["model"] == "gemma3:12b"  # untouched fields keep defaults


class TestRecommendApi:
    def test_empty_wardrobe_returns_gaps_not_500(self, api):
        client, app = api

        class FailingWeather:
            def current(self, city):
                from app.services.weather import WeatherUnavailable

                raise WeatherUnavailable("no net")

        app.state.weather = FailingWeather()
        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "chill", "occasion": "casual"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outfit"] == []
        assert body["gaps"]

    def test_full_flow_with_fallback_stylist(self, api):
        client, app = api
        from tests.conftest import full_wardrobe, FakeWeatherService

        for it in full_wardrobe():
            client.post(
                "/api/items",
                json={
                    "name": it["name"],
                    "type": it["type"],
                    "color": it["color"],
                    "warmth": it["warmth"],
                    "formality": it["formality"],
                    "style_tags": it["style_tags"],
                },
            )
        app.state.weather = FakeWeatherService(temp_c=18.0)

        # Break Ollama so the deterministic fallback kicks in.
        class DownProvider:
            def complete(self, messages, model):
                raise ConnectionError("ollama down")

        app.state.recommender._provider = lambda url: DownProvider()

        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "feeling cosy and chill", "occasion": "casual"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "fallback"
        assert len(body["outfit"]) >= 3
        assert {o["slot"] for o in body["outfit"]} >= {"top", "bottom", "shoes"}
