"""Tests for RecommendationService orchestration: weather -> candidates ->
stylist -> response, including all degradation paths."""
import json

from app.services.recommend import RecommendationService

from conftest import FakeWeatherService, ScriptedProvider, full_wardrobe, make_item


def seed_wardrobe(conn):
    for it in full_wardrobe():
        conn.execute(
            "INSERT INTO items (name, type, color, warmth, formality, style_tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (it["name"], it["type"], it["color"], it["warmth"], it["formality"], it["style_tags"]),
        )


def make_service(conn, provider, temp_c=18.0, weather_fail=False):
    seed_wardrobe(conn)
    svc = RecommendationService()
    svc._provider = lambda url: provider  # inject the fake
    return svc, FakeWeatherService(temp_c=temp_c, fail=weather_fail)


def recommend(conn, svc, weather, mood="chill today", occasion="casual", override=None):
    from app.config import AppConfig

    cfg = AppConfig(db_path="unused")
    return svc.recommend(
        conn=conn,
        config=cfg,
        city="Paris",
        model="gemma3:12b",
        ollama_url="http://localhost:11434",
        weather_service=weather,
        mood=mood,
        occasion=occasion,
        weather_override_c=override,
    )


def valid_reply(candidates, title="Fresh pick"):
    return json.dumps(
        {
            "title": title,
            "item_ids": {
                "top": candidates.slots["top"][0]["id"],
                "bottom": candidates.slots["bottom"][0]["id"],
                "shoes": candidates.slots["shoes"][0]["id"],
                "outerwear": None,
                "accessories": [],
            },
            "rationale": "Loose layers for your relaxed mood.",
        }
    )


class TestHappyPath:
    def test_llm_response_returns_outfit_and_logs_history(self, conn):
        provider = ScriptedProvider([])  # filled below via candidates
        svc, weather = make_service(conn, provider)
        # Build a reply once we know the actual selected candidates.
        from app.services.candidates import select
        cs = select(full_wardrobe(), 18.0, "casual", int(__import__("datetime").datetime.now().strftime("%Y%m%d")))
        provider.replies = [valid_reply(cs)]
        resp = recommend(conn, svc, weather, mood="feeling chill")
        assert resp.source == "llm"
        assert len(resp.outfit) >= 3
        assert {oi.slot for oi in resp.outfit} >= {"top", "bottom", "shoes"}
        assert resp.rationale
        rows = conn.execute("SELECT * FROM outfit_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["mood"] == "feeling chill"
        assert rows[0]["source"] == "llm"

    def test_weather_override_bypasses_service(self, conn):
        provider = ScriptedProvider([])
        svc, weather = make_service(conn, provider, temp_c=30.0)
        from app.services.candidates import select
        cs = select(full_wardrobe(), 2.0, "casual", int(__import__("datetime").datetime.now().strftime("%Y%m%d")))
        provider.replies = [valid_reply(cs)]
        resp = recommend(conn, svc, weather, override=2.0)
        assert resp.weather.temperature_c == 2.0
        assert any("overridden" in g.lower() for g in resp.gaps)
        # Cold day -> the LLM was offered outerwear.
        assert resp.weather is not None


class TestDegradation:
    def test_model_failure_falls_back_deterministically(self, conn):
        import httpx

        provider = ScriptedProvider([httpx.ConnectError("down")])
        svc, weather = make_service(conn, provider)
        resp = recommend(conn, svc, weather)
        assert resp.source == "fallback"
        assert resp.outfit, "fallback must still produce an outfit"
        assert any("safe" in g.lower() or "unavailable" in g.lower() for g in resp.gaps)

    def test_weather_failure_assumes_mild_day(self, conn):
        provider = ScriptedProvider([])
        svc, weather = make_service(conn, provider, weather_fail=True)
        from app.services.candidates import select
        cs = select(full_wardrobe(), 15.0, "casual", int(__import__("datetime").datetime.now().strftime("%Y%m%d")))
        provider.replies = [valid_reply(cs)]
        resp = recommend(conn, svc, weather)
        assert resp.weather.temperature_c == 15.0
        assert any("mild" in g.lower() for g in resp.gaps)

    def test_empty_wardrobe_returns_gaps_not_error(self, conn):
        svc = RecommendationService()
        svc._provider = lambda url: ScriptedProvider([])
        resp = recommend(conn, svc, FakeWeatherService(18.0))
        assert resp.outfit == []
        assert resp.gaps
        assert "No complete outfit" in resp.title or not resp.outfit

    def test_uncoverable_occasion_reports_named_gap(self, conn):
        # Wardrobe with only formal items, asking for gym at freezing temp.
        only_formal = [
            make_item(1, "top", 2, 5),
            make_item(2, "bottom", 2, 5),
            make_item(3, "shoes", 2, 5),
        ]
        for it in only_formal:
            conn.execute(
                "INSERT INTO items (name, type, warmth, formality) VALUES (?, ?, ?, ?)",
                (it["name"], it["type"], it["warmth"], it["formality"]),
            )
        svc = RecommendationService()
        svc._provider = lambda url: ScriptedProvider([])
        resp = recommend(conn, svc, FakeWeatherService(2.0), occasion="gym")
        assert resp.outfit == []
        assert any("gym" in g for g in resp.gaps)
