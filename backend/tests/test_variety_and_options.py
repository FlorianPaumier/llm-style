"""Tests for variety between recommendations and the count/options feature.

Variety: re-asking the same prompt must not repeat the same outfit — the
stylist prompt carries a "do not repeat" memory (recent history + earlier
options in the same request), and the deterministic fallback rotates away
from avoided item ids while a slot has alternatives.

Options: RecommendRequest.count (1-5) asks for several outfit options per
persona; each option differs from the ones before it and logs its own
history entry.
"""
import json

import httpx
import pytest

from app.services import stylist
from app.services.candidates import select
from app.services.recommend import RecommendationService

from conftest import FakeWeatherService, ScriptedProvider, full_wardrobe, make_item


SEED = 20260905


def seed_items(conn, items):
    for it in items:
        conn.execute(
            "INSERT INTO items (name, type, color, warmth, formality, style_tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (it["name"], it["type"], it["color"], it["warmth"], it["formality"],
             it["style_tags"]),
        )


def make_service(conn, provider, temp_c=18.0):
    svc = RecommendationService()
    svc.provider_for = lambda url: provider  # inject the fake
    return svc, FakeWeatherService(temp_c=temp_c)


def recommend(conn, svc, weather, *, mood="chill today", occasion="casual",
              override=None, count=1, rng_seed=SEED):
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
        weather_override_c=override,
        count=count,
        rng_seed=rng_seed,
    )


def seeded_conn(conn):
    """A wardrobe rich enough that every slot has in-band alternatives."""
    seed_items(conn, full_wardrobe())
    return conn


class TestPromptVarietyMemory:
    def test_prompt_lists_recent_outfits_when_given(self):
        cs = select(full_wardrobe(), temp_c=18.0, occasion="casual", rng_seed=SEED)
        p = stylist.build_prompt(
            cs, mood="dreamy", occasion="casual",
            recent_outfits=["white tee, blue jeans", "navy shirt, chinos"],
        )
        assert "Already suggested recently" in p
        assert "white tee, blue jeans" in p
        assert "do not repeat" in p.lower()
        assert "never" in p  # the hard variety rule
        # The memory sits in Today's context, before the candidates.
        assert p.index("Already suggested recently") < p.index("Candidate items")

    def test_prompt_without_recent_outfits_has_no_memory_section(self):
        cs = select(full_wardrobe(), temp_c=18.0, occasion="casual", rng_seed=SEED)
        p = stylist.build_prompt(cs, mood="dreamy", occasion="casual")
        assert "Already suggested recently" not in p
        # The base nudge is still there: aim for the best mix, not the safest.
        assert "best mix" in p

    def test_choose_passes_recent_outfits_to_prompt(self):
        cs = select(full_wardrobe(), temp_c=18.0, occasion="casual", rng_seed=SEED)
        reply = json.dumps({
            "title": "t", "item_ids": {
                "top": cs.slots["top"][0]["id"],
                "bottom": cs.slots["bottom"][0]["id"],
                "shoes": cs.slots["shoes"][0]["id"],
            }, "rationale": "r",
        })
        provider = ScriptedProvider([reply])
        stylist.choose(
            provider, "m", cs, "chill", "casual",
            recent_outfits=["grey hoodie, jeans"],
        )
        assert "grey hoodie, jeans" in provider.calls[0][-1]["content"]


class TestFallbackAvoid:
    def test_fallback_avoids_recently_suggested_when_alternatives_exist(self):
        # Two identical in-band tops; avoiding id 1 must move the pick to 2.
        items = [
            make_item(1, "top", 2, 2), make_item(2, "top", 2, 2),
            make_item(3, "bottom", 2, 2),
            make_item(4, "shoes", 2, 2),
        ]
        cs = select(items, temp_c=18.0, occasion="casual", rng_seed=SEED)
        choice = stylist.fallback_choice(cs, avoid={1})
        assert choice.slot_picks["top"] == 2

    def test_fallback_still_picks_avoided_item_when_slot_has_no_alternative(self):
        # Only one top: variety must never dead-end a small wardrobe.
        items = [
            make_item(1, "top", 2, 2),
            make_item(2, "bottom", 2, 2),
            make_item(3, "shoes", 2, 2),
        ]
        cs = select(items, temp_c=18.0, occasion="casual", rng_seed=SEED)
        choice = stylist.fallback_choice(cs, avoid={1, 2, 3})
        assert choice.slot_picks == {"top": 1, "bottom": 2, "shoes": 3}

    def test_fallback_formality_priority_survives_avoid(self):
        # The avoided id is the formal closest; the alternative must still
        # respect formality distance over a worse-fitting fresh item.
        items = [
            make_item(1, "top", 2, 2),   # formality 2 = target for casual
            make_item(2, "top", 2, 2),   # same distance, higher id
            make_item(3, "top", 2, 5),   # fresh but far from target
        ]
        cs = select(items, temp_c=18.0, occasion="casual", rng_seed=SEED)
        choice = stylist.fallback_choice(cs, avoid={1})
        assert choice.slot_picks["top"] == 2  # not 3: fit still beats variety


class TestRecentItemIds:
    def test_recent_item_ids_newest_last_and_persona_scoped(self, conn):
        seed_items(conn, full_wardrobe())
        from app.repo import history as history_repo

        history_repo.add(conn, "m1", "casual", None, [1, 9], "r", "llm", persona_id=1)
        history_repo.add(conn, "m2", "casual", None, [17, 25], "r", "llm", persona_id=1)
        history_repo.add(conn, "m3", "casual", None, [1], "r", "llm", persona_id=2)

        got = history_repo.recent_item_ids(conn, 1, limit=3)
        assert got == [[1, 9], [17, 25]]  # oldest first, only persona 1

    def test_recent_item_ids_skips_empty_and_bad_rows(self, conn):
        from app.repo import history as history_repo

        history_repo.add(conn, "m", "casual", None, [], "r", "fallback", persona_id=1)
        assert history_repo.recent_item_ids(conn, 1) == []


class TestCountOptions:
    def test_count_three_fallback_yields_three_distinct_outfits(self, conn):
        seeded_conn(conn)
        provider = ScriptedProvider([httpx.ConnectError("down")])  # all fallback
        svc, weather = make_service(conn, provider)
        resp = recommend(conn, svc, weather, count=3)
        assert len(resp.outfits) == 3
        assert [o.option for o in resp.outfits] == [1, 2, 3]
        sets = [frozenset(oi.item.id for oi in o.outfit) for o in resp.outfits]
        assert len(set(sets)) == 3, "options must not repeat the same combination"
        for o in resp.outfits:
            assert {oi.slot for oi in o.outfit} >= {"top", "bottom", "shoes"}

    def test_count_logs_history_per_option(self, conn):
        seeded_conn(conn)
        provider = ScriptedProvider([httpx.ConnectError("down")])
        svc, weather = make_service(conn, provider)
        recommend(conn, svc, weather, count=3)
        rows = conn.execute("SELECT COUNT(*) AS n FROM outfit_history").fetchone()
        assert rows["n"] == 3

    def test_count_one_matches_legacy_behaviour(self, conn):
        seeded_conn(conn)
        provider = ScriptedProvider([httpx.ConnectError("down")])
        svc, weather = make_service(conn, provider)
        resp = recommend(conn, svc, weather, count=1)
        assert len(resp.outfits) == 1
        assert resp.outfits[0].option == 1
        assert resp.history_id == resp.outfits[0].history_id

    def test_option_two_prompt_mentions_option_one(self, conn):
        seeded_conn(conn)
        # Script two valid replies; both must be based on the same candidates
        # (one select per persona, options share the pool).
        from app.services.candidates import select as sel

        cs = sel(full_wardrobe(), 18.0, "casual", SEED)

        def reply(n):
            return json.dumps({
                "title": f"Outfit {n}",
                "item_ids": {
                    "top": cs.slots["top"][n % len(cs.slots["top"])]["id"],
                    "bottom": cs.slots["bottom"][n % len(cs.slots["bottom"])]["id"],
                    "shoes": cs.slots["shoes"][n % len(cs.slots["shoes"])]["id"],
                },
                "rationale": "r",
            })

        provider = ScriptedProvider([reply(0), reply(1)])
        svc, weather = make_service(conn, provider)
        resp = recommend(conn, svc, weather, count=2)
        assert len(provider.calls) == 2
        second_prompt = provider.calls[1][-1]["content"]
        assert "Outfit 1" in second_prompt or "do not repeat" in second_prompt
        assert "Already suggested recently" in second_prompt
        assert resp.outfits[1].source == "llm"

    def test_history_feeds_next_request_memory(self, conn):
        seeded_conn(conn)
        provider = ScriptedProvider([httpx.ConnectError("down")])
        svc, weather = make_service(conn, provider)
        recommend(conn, svc, weather, count=1)
        # Second ask: the fallback must rotate away from the first outfit.
        provider2 = ScriptedProvider([httpx.ConnectError("down")])
        svc2, weather2 = make_service(conn, provider2)
        r1 = conn.execute("SELECT item_ids_json FROM outfit_history ORDER BY id").fetchone()
        first_ids = set(json.loads(r1["item_ids_json"]))
        resp = recommend(conn, svc2, weather2, count=1)
        second_ids = {oi.item.id for oi in resp.outfits[0].outfit}
        assert second_ids != first_ids, "a repeated ask must not repeat the outfit"

    def test_pair_mode_times_count_gives_four_cards(self, conn):
        seeded_conn(conn)
        from app.repo import personas as personas_repo

        partner = personas_repo.create(conn, "Partner")
        seed_items(conn, full_wardrobe())  # partner shares the seed for simplicity
        conn.execute("UPDATE items SET persona_id = ? WHERE id <= 20", (partner["id"],))
        provider = ScriptedProvider([httpx.ConnectError("down")] * 4)
        svc, weather = make_service(conn, provider)
        from app.config import AppConfig

        cfg = AppConfig(db_path="unused")
        resp = svc.recommend(
            conn=conn, config=cfg, city="Paris", model="m",
            ollama_url="http://x", weather_service=weather,
            mood="pair day", occasion="casual",
            persona_ids=[1, partner["id"]], count=2, rng_seed=SEED,
        )
        assert len(resp.outfits) == 4
        assert [o.option for o in resp.outfits] == [1, 2, 1, 2]
        assert [o.persona_name for o in resp.outfits] == ["Me", "Me", "Partner", "Partner"]
        # Partner's option 1 card is complete (coordinated, not starved).
        partner_cards = [o for o in resp.outfits if o.persona_name == "Partner"]
        for o in partner_cards:
            assert {oi.slot for oi in o.outfit} >= {"top", "bottom", "shoes"}


class TestCountValidation:
    def test_count_zero_rejected(self, api):
        client, _ = api
        r = client.post(
            "/api/outfits/recommend", json={"mood": "chill", "count": 0}
        )
        assert r.status_code == 422

    def test_count_six_rejected(self, api):
        client, _ = api
        r = client.post(
            "/api/outfits/recommend", json={"mood": "chill", "count": 6}
        )
        assert r.status_code == 422

    def test_count_three_accepted(self, api):
        client, _ = api
        r = client.post(
            "/api/outfits/recommend", json={"mood": "chill", "count": 3}
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["outfits"]) == 3
