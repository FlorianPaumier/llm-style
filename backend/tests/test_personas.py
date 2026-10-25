"""Multi-persona tests: separation, pairing, guards, backward compat."""
import datetime
import json

from app.services.candidates import select

from conftest import FakeWeatherService, ScriptedProvider, full_wardrobe


# Payloads carry a category per broad type (the API requires one); the
# catch-all keeps these tests about persona behavior, not taxonomy.
CATEGORY_OF_TYPE = {
    "top": "other_top", "bottom": "other_bottom", "shoes": "other_shoes",
    "outerwear": "other_outerwear", "accessory": "other_accessory",
}


def seed_persona(client, persona_id, items):
    """Create items under a persona from (name, type, warmth, formality) tuples."""
    ids = []
    for name, type_, warmth, formality in items:
        r = client.post(
            "/api/items",
            json={
                "name": name, "category": CATEGORY_OF_TYPE[type_],
                "type": type_, "color": "blue",
                "warmth": warmth, "formality": formality,
                "persona_id": persona_id,
            },
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


# Two complete mini-wardrobes with distinct names, both covering all slots.
HIS = [
    ("His tee", "top", 2, 2), ("His jeans", "bottom", 2, 2), ("His sneakers", "shoes", 2, 2),
]
HERS = [
    ("Her blouse", "top", 2, 2), ("Her skirt", "bottom", 2, 2), ("Her flats", "shoes", 2, 2),
]


def valid_reply_for(candidates, title="pick"):
    return json.dumps({
        "title": title,
        "item_ids": {
            "top": candidates.slots["top"][0]["id"],
            "bottom": candidates.slots["bottom"][0]["id"],
            "shoes": candidates.slots["shoes"][0]["id"],
            "outerwear": None,
            "accessories": [],
        },
        "rationale": "x",
    })


def wardrobe_rows(client, persona_id=None):
    """Item rows exactly as the recommender sees them for a persona."""
    import sqlite3
    from app.db import connect
    # Go through the API to also assert the envelope contract.
    if persona_id:
        body = client.get(f"/api/items?persona_id={persona_id}").json()
    else:
        body = client.get("/api/items").json()
    return body["items"]


class TestPersonaCrud:
    def test_default_persona_exists(self, api):
        client, _ = api
        personas = client.get("/api/personas").json()
        assert personas == [
            {"id": 1, "name": "Me", "description": None, "gender": "unspecified"}
        ]

    def test_create_rename_delete_roundtrip(self, api):
        client, _ = api
        r = client.post("/api/personas", json={"name": "Alice"})
        assert r.status_code == 201
        assert r.json() == {
            "id": 2, "name": "Alice", "description": None, "gender": "unspecified"
        }
        r = client.put("/api/personas/2", json={"name": "Alicia"})
        assert r.json()["name"] == "Alicia"
        assert client.delete("/api/personas/2").status_code == 204
        assert client.get("/api/personas").json()[0]["id"] == 1

    def test_rename_404(self, api):
        client, _ = api
        assert client.put("/api/personas/99", json={"name": "x"}).status_code == 404

    def test_cannot_delete_last_persona(self, api):
        client, _ = api
        r = client.delete("/api/personas/1")
        assert r.status_code == 400
        assert "last" in r.json()["detail"]

    def test_cannot_delete_persona_with_items(self, api):
        client, _ = api
        client.post("/api/personas", json={"name": "Bob"})  # so 1 isn't the last
        seed_persona(client, 1, HIS)
        r = client.delete("/api/personas/1")
        assert r.status_code == 409
        # But an empty persona deletes fine.
        assert client.delete("/api/personas/2").status_code == 204

    def test_name_validation(self, api):
        client, _ = api
        assert client.post("/api/personas", json={"name": ""}).status_code == 422
        assert client.post("/api/personas", json={"name": "x" * 51}).status_code == 422

    def test_create_with_description_roundtrip(self, api):
        client, _ = api
        r = client.post(
            "/api/personas",
            json={"name": "Alice", "description": "no hats — they don't suit me"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["description"] == "no hats — they don't suit me"
        # And it is visible on GET, not just the create echo.
        personas = client.get("/api/personas").json()
        assert [p for p in personas if p["id"] == r.json()["id"]][0][
            "description"
        ] == "no hats — they don't suit me"

    def test_description_put_semantics(self, api):
        """PUT merge semantics: absent key keeps, sent key (even null/"")
        sets/clears, text replaces; untouched name stays."""
        client, _ = api
        pid = client.post(
            "/api/personas",
            json={"name": "Alice", "description": "no hats"},
        ).json()["id"]

        # Absent description key: keeps current value (name-only PUT).
        r = client.put(f"/api/personas/{pid}", json={"name": "Alicia"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Alicia"
        assert r.json()["description"] == "no hats"

        # Sent text replaces.
        r = client.put(
            f"/api/personas/{pid}",
            json={"description": "prefers bold colors"},
        )
        assert r.json()["description"] == "prefers bold colors"
        assert r.json()["name"] == "Alicia"  # name key absent -> untouched

        # Explicit null clears; name absent keeps.
        r = client.put(f"/api/personas/{pid}", json={"description": None})
        assert r.json()["description"] is None
        assert r.json()["name"] == "Alicia"

        # Re-set, then "" also clears.
        r = client.put(f"/api/personas/{pid}", json={"description": "dislikes skirts"})
        assert r.json()["description"] == "dislikes skirts"
        r = client.put(f"/api/personas/{pid}", json={"description": ""})
        assert r.json()["description"] is None

        # Both at once still works.
        r = client.put(
            f"/api/personas/{pid}",
            json={"name": "Alice", "description": "prefers bold colors"},
        )
        assert r.json() == {
            "id": pid, "name": "Alice", "description": "prefers bold colors",
            "gender": "unspecified",
        }

        # Empty PUT body {} keeps everything (all keys absent).
        r = client.put(f"/api/personas/{pid}", json={})
        assert r.json() == {
            "id": pid, "name": "Alice", "description": "prefers bold colors",
            "gender": "unspecified",
        }

        # Explicit null name keeps the name (a name can never be cleared).
        r = client.put(f"/api/personas/{pid}", json={"name": None})
        assert r.json()["name"] == "Alice"
        # ...and an empty name is still rejected.
        assert client.put(
            f"/api/personas/{pid}", json={"name": ""}
        ).status_code == 422

    def test_gender_semantics(self, api):
        """gender: optional on create (default unspecified); PUT merge —
        absent keeps, a sent value sets, null resets to unspecified;
        anything outside the enum is 422."""
        client, _ = api
        r = client.post(
            "/api/personas", json={"name": "Anna", "gender": "female"}
        )
        assert r.status_code == 201, r.text
        assert r.json()["gender"] == "female"
        pid = r.json()["id"]

        # Absent key keeps.
        assert client.put(f"/api/personas/{pid}", json={"name": "Anna"}).json()[
            "gender"
        ] == "female"
        # A sent value replaces.
        assert client.put(f"/api/personas/{pid}", json={"gender": "male"}).json()[
            "gender"
        ] == "male"
        # Null resets to unspecified.
        assert client.put(f"/api/personas/{pid}", json={"gender": None}).json()[
            "gender"
        ] == "unspecified"
        # Invalid values are rejected on create and update.
        for bad in ("robot", "M", 1):
            assert client.post(
                "/api/personas", json={"name": "X", "gender": bad}
            ).status_code == 422
            assert client.put(
                f"/api/personas/{pid}", json={"gender": bad}
            ).status_code == 422

        # Description and gender can be set together.
        r = client.post(
            "/api/personas",
            json={"name": "Bo", "gender": "male", "description": "no hats"},
        )
        assert r.json()["gender"] == "male"
        assert r.json()["description"] == "no hats"

    def test_description_validation(self, api):
        client, _ = api
        # Too long -> 422 (both on create and update).
        long = "x" * 501
        assert client.post(
            "/api/personas", json={"name": "A", "description": long}
        ).status_code == 422
        assert client.put(
            "/api/personas/1", json={"description": long}
        ).status_code == 422
        # Unknown keys still forbidden.
        assert client.post(
            "/api/personas", json={"name": "A", "surprise": 1}
        ).status_code == 422
        assert client.put(
            "/api/personas/1", json={"surprise": 1}
        ).status_code == 422


class TestWardrobeSeparation:
    def test_items_scoped_by_persona(self, api):
        client, _ = api
        his = seed_persona(client, 1, HIS)
        hers = seed_persona(client, 2, HERS) if len(
            client.get("/api/personas").json()
        ) >= 2 else None
        # ensure persona 2 exists
        if hers is None:
            client.post("/api/personas", json={"name": "Her"})
            hers = seed_persona(client, 2, HERS)

        # Persona 1's default view (no param) sees only HIS items.
        default_view = wardrobe_rows(client)
        assert {i["id"] for i in default_view} == set(his)
        assert all(i["name"].startswith("His") for i in default_view)

        p1 = wardrobe_rows(client, persona_id=1)
        p2 = wardrobe_rows(client, persona_id=2)
        assert {i["id"] for i in p1} == set(his)
        assert {i["id"] for i in p2} == set(hers)
        assert not ({i["id"] for i in p1} & {i["id"] for i in p2})

    def test_move_item_between_personas(self, api):
        client, _ = api
        client.post("/api/personas", json={"name": "Her"})
        [item_id] = seed_persona(client, 1, [("Shared-to-be tee", "top", 2, 2)])
        # PUT with persona_id moves it; PUT without keeps it where it is.
        r = client.put(
            f"/api/items/{item_id}",
            json={"name": "Shared-to-be tee", "category": "other_top",
                  "type": "top", "color": "blue",
                  "warmth": 2, "formality": 2, "persona_id": 2},
        )
        assert r.status_code == 200 and r.json()["persona_id"] == 2
        r = client.put(
            f"/api/items/{item_id}",
            json={"name": "Shared-to-be tee v2", "category": "other_top",
                  "type": "top", "color": "blue",
                  "warmth": 2, "formality": 2},
        )
        assert r.json()["persona_id"] == 2  # untouched field keeps wardrobe
        assert client.get("/api/items?persona_id=1").json()["total"] == 0

    def test_move_to_unknown_persona_422(self, api):
        client, _ = api
        [item_id] = seed_persona(client, 1, HIS[:1])
        r = client.put(
            f"/api/items/{item_id}",
            json={"name": "x", "category": "other_top", "type": "top",
                  "warmth": 2, "formality": 2, "persona_id": 99},
        )
        assert r.status_code == 422

    def test_create_with_unknown_persona_422(self, api):
        client, _ = api
        r = client.post(
            "/api/items",
            json={"name": "x", "category": "other_top", "type": "top",
                  "warmth": 2, "formality": 2, "persona_id": 99},
        )
        assert r.status_code == 422

    def test_backward_compat_no_params_means_persona_1(self, api):
        client, _ = api
        client.post("/api/personas", json={"name": "Her"})
        his = seed_persona(client, 1, HIS)
        seed_persona(client, 2, HERS)
        # No persona_id anywhere: items default to persona 1.
        r = client.post(
            "/api/items",
            json={"name": "His extra tee", "category": "other_top",
                  "type": "top", "warmth": 2, "formality": 2},
        )
        assert r.json()["persona_id"] == 1
        # And the default list equals persona 1's list.
        assert wardrobe_rows(client) == wardrobe_rows(client, persona_id=1)


class TestPairedRecommendations:
    def setup_wardrobes(self, client, app):
        client.post("/api/personas", json={"name": "Her"})
        his_ids = seed_persona(client, 1, HIS)
        her_ids = seed_persona(client, 2, HERS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        return his_ids, her_ids

    def valid_pair_replies(self, conn):
        """Two scripted replies, each referencing real candidates."""
        from app.db import connect as _c
        from app.repo import items as items_repo

        def rows_for(persona_id):
            return [
                dict(r) for r in conn.execute(
                    "SELECT * FROM items WHERE persona_id = ? ORDER BY id", (persona_id,)
                )
            ]

        his_rows = rows_for(1)
        her_rows = rows_for(2)
        his_cs = select(his_rows, 18.0, "casual", 20260904)
        her_cs = select(her_rows, 18.0, "casual", 20260904)
        return [valid_reply_for(his_cs, "His pick"), valid_reply_for(her_cs, "Her pick")]

    def test_pair_returns_two_scoped_outfits(self, api):
        client, app = api
        his_ids, her_ids = self.setup_wardrobes(client, app)

        provider = ScriptedProvider([])
        app.state.recommender.provider_for = lambda url: provider
        # Build replies after seeding; same-day seed as the service uses.
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect
        conn = connect(app.state.config.db_path)
        his_rows = items_repo.list_all(conn, persona_id=1)
        her_rows = items_repo.list_all(conn, persona_id=2)
        conn.close()
        provider.replies = [
            valid_reply_for(select(his_rows, 18.0, "casual", seed), "His pick"),
            valid_reply_for(select(her_rows, 18.0, "casual", seed), "Her pick"),
        ]

        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "date night", "occasion": "casual", "persona_ids": [1, 2]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["outfits"]) == 2

        o1, o2 = body["outfits"]
        assert o1["persona_id"] == 1 and o1["title"] == "His pick"
        assert o2["persona_id"] == 2 and o2["title"] == "Her pick"
        ids1 = {piece["item"]["id"] for piece in o1["outfit"]}
        ids2 = {piece["item"]["id"] for piece in o2["outfit"]}
        assert ids1 <= set(his_ids), "persona 1's outfit must be his clothes only"
        assert ids2 <= set(her_ids), "persona 2's outfit must be her clothes only"

        # Top-level compat fields mirror the first persona.
        assert body["title"] == "His pick"
        assert {p["item"]["id"] for p in body["outfit"]} == ids1
        assert body["history_id"] == o1["history_id"]

        # Two history rows, one per persona.
        hist = client.get("/api/history").json()
        assert {h["persona_id"] for h in hist} == {1, 2}
        hist2 = client.get("/api/history?persona_id=2").json()
        assert all(h["persona_id"] == 2 for h in hist2)

    def test_second_call_gets_coordination_context(self, api):
        client, app = api
        his_ids, her_ids = self.setup_wardrobes(client, app)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect
        conn = connect(app.state.config.db_path)
        his_rows = items_repo.list_all(conn, persona_id=1)
        her_rows = items_repo.list_all(conn, persona_id=2)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(her_rows, 18.0, "casual", seed), "Her pick"),
            valid_reply_for(select(his_rows, 18.0, "casual", seed), "His pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        client.post(
            "/api/outfits/recommend",
            json={"mood": "date night", "persona_ids": [2, 1]},  # Her first
        )
        assert len(provider.calls) == 2
        second_prompt = provider.calls[1][-1]["content"]
        # The second persona's prompt must see the first one's outfit.
        assert "already wearing" in second_prompt
        assert "Her blouse" in second_prompt or "Her skirt" in second_prompt
        # ...and the first persona's prompt has no coordination context.
        assert "already wearing" not in provider.calls[0][-1]["content"]

    def test_single_persona_behaves_as_before(self, api):
        client, app = api
        his_ids, _ = self.setup_wardrobes(client, app)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect
        conn = connect(app.state.config.db_path)
        his_rows = items_repo.list_all(conn, persona_id=1)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(his_rows, 18.0, "casual", seed), "Solo pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        r = client.post("/api/outfits/recommend", json={"mood": "chill"})
        body = r.json()
        assert len(body["outfits"]) == 1
        assert body["outfits"][0]["persona_id"] == 1
        # No coordination context on a solo run.
        assert "already wearing" not in provider.calls[0][-1]["content"]

    def test_pair_falls_back_deterministically_per_persona(self, api):
        client, app = api
        self.setup_wardrobes(client, app)

        class Down:
            def complete(self, messages, model, temperature=0.7):
                raise ConnectionError("down")

        app.state.recommender.provider_for = lambda url: Down()

        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "chill", "persona_ids": [1, 2]},
        )
        body = r.json()
        assert len(body["outfits"]) == 2
        assert all(o["source"] == "fallback" for o in body["outfits"])
        assert all(len(o["outfit"]) >= 3 for o in body["outfits"])
        ids1 = {p["item"]["id"] for p in body["outfits"][0]["outfit"]}
        ids2 = {p["item"]["id"] for p in body["outfits"][1]["outfit"]}
        his_ids = {i["id"] for i in wardrobe_rows(client, persona_id=1)}
        her_ids = {i["id"] for i in wardrobe_rows(client, persona_id=2)}
        assert ids1 <= his_ids and ids2 <= her_ids

    def test_unknown_persona_422(self, api):
        client, _ = api
        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "chill", "persona_ids": [99]},
        )
        assert r.status_code == 422, r.text


class TestPersonaDescriptionReachesStylist:
    def test_description_in_llm_prompt(self, api):
        client, app = api
        seed_persona(client, 1, HIS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect

        conn = connect(app.state.config.db_path)
        rows = items_repo.list_all(conn, persona_id=1)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(rows, 18.0, "casual", seed), "Hat-free pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        # Set a description, then recommend for that persona.
        client.put("/api/personas/1", json={"description": "no hats — they don't suit me"})
        r = client.post("/api/outfits/recommend", json={"mood": "date night"})
        assert r.status_code == 200, r.text

        # The description must reach the LLM in the user prompt...
        user_msg = provider.calls[0][-1]["content"]
        assert "no hats — they don't suit me" in user_msg
        assert "respect these preferences" in user_msg
        assert r.json()["outfits"][0]["title"] == "Hat-free pick"

    def test_gender_in_llm_prompt(self, api):
        """The persona's gender reaches the stylist prompt through the
        recommend flow; unspecified personas add no note."""
        client, app = api
        seed_persona(client, 1, HIS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect

        conn = connect(app.state.config.db_path)
        rows = items_repo.list_all(conn, persona_id=1)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(rows, 18.0, "casual", seed), "Gendered pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        client.put("/api/personas/1", json={"gender": "female"})
        r = client.post("/api/outfits/recommend", json={"mood": "date night"})
        assert r.status_code == 200, r.text
        user_msg = provider.calls[0][-1]["content"]
        assert "This person is a woman" in user_msg

    def test_no_description_no_notes_line(self, api):
        client, app = api
        seed_persona(client, 1, HIS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect

        conn = connect(app.state.config.db_path)
        rows = items_repo.list_all(conn, persona_id=1)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(rows, 18.0, "casual", seed), "Solo pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        r = client.post("/api/outfits/recommend", json={"mood": "chill"})
        assert r.status_code == 200, r.text
        # No description set -> no persona-notes line in the prompt.
        user_msg = provider.calls[0][-1]["content"]
        assert "Notes about this person" not in user_msg
        assert "respect these preferences" not in user_msg

    def test_fallback_ignores_description(self, api):
        """Description steers the LLM only; the deterministic fallback and
        the candidate set are unchanged by it."""
        client, app = api
        seed_persona(client, 1, HIS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        client.put("/api/personas/1", json={"description": "no hats, hates jeans"})

        class Down:
            def complete(self, messages, model, temperature=0.7):
                raise ConnectionError("down")

        app.state.recommender.provider_for = lambda url: Down()
        r = client.post("/api/outfits/recommend", json={"mood": "chill"})
        body = r.json()
        assert body["source"] == "fallback"
        # Same deterministic pick as with no description: the closest-
        # formality item per slot, which here is each of HIS pieces.
        assert {p["item"]["name"] for p in body["outfit"]} == {
            "His tee", "His jeans", "His sneakers",
        }


class TestPairAsyncJob:
    def test_pair_async(self, api):
        client, app = api
        client.post("/api/personas", json={"name": "Her"})
        his_ids = seed_persona(client, 1, HIS)
        her_ids = seed_persona(client, 2, HERS)
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        from app.repo import items as items_repo
        from app.db import connect
        conn = connect(app.state.config.db_path)
        his_rows = items_repo.list_all(conn, persona_id=1)
        her_rows = items_repo.list_all(conn, persona_id=2)
        conn.close()
        provider = ScriptedProvider([
            valid_reply_for(select(his_rows, 18.0, "casual", seed), "His pick"),
            valid_reply_for(select(her_rows, 18.0, "casual", seed), "Her pick"),
        ])
        app.state.recommender.provider_for = lambda url: provider

        r = client.post(
            "/api/outfits/recommend/async",
            json={"mood": "date night", "persona_ids": [1, 2]},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st["status"] in ("done", "failed"):
                break
        assert st["status"] == "done", st
        assert len(st["result"]["outfits"]) == 2
