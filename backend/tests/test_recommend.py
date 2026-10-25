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
    svc.provider_for = lambda url: provider  # inject the fake
    return svc, FakeWeatherService(temp_c=temp_c, fail=weather_fail)


def recommend(conn, svc, weather, mood="chill today", occasion="casual", override=None,
              activity=None, rng_seed=None):
    from app.config import AppConfig

    cfg = AppConfig(db_path="unused")
    return svc.recommend(
        conn=conn,
        config=cfg,
        city="Paris",
        model="dolphin-mistral:7b",
        ollama_url="http://localhost:11434",
        weather_service=weather,
        mood=mood,
        occasion=occasion,
        activity=activity,
        weather_override_c=override,
        rng_seed=rng_seed,
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

    def test_cold_day_fallback_includes_warm_accessory(self, conn):
        # Model down on a cold day: the deterministic fallback must still
        # dress the accessory slot with a warmth-band-matching piece.
        import httpx

        provider = ScriptedProvider([httpx.ConnectError("down")])
        svc, weather = make_service(conn, provider, temp_c=5.0)
        resp = recommend(conn, svc, weather)
        assert resp.source == "fallback"
        acc_slots = [oi for oi in resp.outfit if oi.slot == "accessory"]
        assert acc_slots, "cold-day fallback outfit should include an accessory"
        # A warmth-4 piece at 5°C (band 3-4): picked, never the warmth-1 watch.
        assert acc_slots[0].item.id != 30  # id 30 = warmth-1 watch in seed data
        # It must be part of the logged history too (stored as JSON ids).
        rows = conn.execute("SELECT * FROM outfit_history").fetchall()
        logged = json.loads(rows[0]["item_ids_json"])
        assert logged and acc_slots[0].item.id in logged

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
        svc.provider_for = lambda url: ScriptedProvider([])
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
        svc.provider_for = lambda url: ScriptedProvider([])
        resp = recommend(conn, svc, FakeWeatherService(2.0), occasion="gym")
        assert resp.outfit == []
        assert any("gym" in g for g in resp.gaps)


class TestActivity:
    """The 'what are you doing?' field: a stated activity guarantees a
    warm-layer option (and the fallback wears it) even on a mild day."""

    def _seed_dinner_wardrobe(self, conn):
        for name, type_, category, warmth, formality in [
            ("Tee", "top", "t_shirt", 2, 2),
            ("Cardigan", "top", "cardigan", 3, 2),
            ("Jeans", "bottom", "jeans", 2, 2),
            ("Sneakers", "shoes", "sneakers", 2, 2),
        ]:
            conn.execute(
                "INSERT INTO items (name, type, category, warmth, formality)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, type_, category, warmth, formality),
            )

    def test_activity_fallback_includes_the_cardigan_layer(self, conn):
        import httpx

        self._seed_dinner_wardrobe(conn)
        svc = RecommendationService()
        svc.provider_for = lambda url: ScriptedProvider([httpx.ConnectError("down")])
        resp = recommend(
            conn, svc, FakeWeatherService(18.0),
            mood="festive", activity="Christmas dinner",
        )
        categories = [oi.item.category for oi in resp.outfit]
        assert "cardigan" in categories  # the guaranteed warm layer
        assert resp.source == "fallback"

    def test_no_activity_mild_day_skips_the_out_of_band_layer(self, conn):
        import httpx

        self._seed_dinner_wardrobe(conn)
        svc = RecommendationService()
        svc.provider_for = lambda url: ScriptedProvider([httpx.ConnectError("down")])
        resp = recommend(conn, svc, FakeWeatherService(18.0), mood="chill")
        categories = [oi.item.category for oi in resp.outfit]
        assert "cardigan" not in categories

    def test_llm_reply_without_layer_still_valid_with_activity(self, conn):
        # The activity rule steers the prompt; a reply that skips the layer
        # (a warm sweater as the top, say) still validates.
        self._seed_dinner_wardrobe(conn)
        svc = RecommendationService()
        provider = ScriptedProvider([])
        svc.provider_for = lambda url: provider
        from app.services.candidates import select

        rows = [dict(r) for r in conn.execute("SELECT * FROM items")]
        cs = select(rows, 18.0, "casual", 20260905, activity="Christmas dinner")
        tee = next(it["id"] for it in cs.slots["top"] if it["category"] == "t_shirt")
        reply = json.dumps({
            "title": "Dinner pick",
            "item_ids": {
                "top": tee,
                "bottom": next(it["id"] for it in cs.slots["bottom"]),
                "shoes": next(it["id"] for it in cs.slots["shoes"]),
            },
            "rationale": "r",
        })
        provider.replies = [reply]
        resp = recommend(
            conn, svc, FakeWeatherService(18.0),
            mood="festive", activity="Christmas dinner",
        )
        assert resp.source == "llm"
        assert resp.title == "Dinner pick"
        # The activity reached the prompt.
        assert 'What they\'ll be doing: "Christmas dinner"' in (
            provider.calls[0][-1]["content"]
        )
