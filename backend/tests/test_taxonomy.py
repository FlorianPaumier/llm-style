"""Detailed garment taxonomy: category metadata, API validation, database
backfill, vision-draft category handling, role-constrained stylist
validation and fallback, candidate completeness, and end-to-end role
behavior (vest/blouse conflict, skirt+tights, layering, one-piece)."""
import json

import pytest

from app.categories import (
    CATEGORIES,
    CATEGORY_ROLE,
    CATEGORY_SLOT,
    ROLE_LAYER_UPPER,
    ROLE_LOWER_UNDERLAYER,
    ROLE_ONE_PIECE,
    ROLE_PRIMARY_LOWER,
    ROLE_PRIMARY_UPPER,
    SLOT_CATEGORIES,
    default_category,
    item_role,
)
from app.db import init_db
from app.services import classify, stylist
from app.services.candidates import select
from app.services.recommend import RecommendationService

from conftest import FakeWeatherService, ScriptedProvider, make_item

SEED = 20260905


def taxo_wardrobe(*specs):
    """Build items from (type, category, warmth, formality) tuples."""
    return [
        make_item(i + 1, type_, warmth, formality, category=category)
        for i, (type_, category, warmth, formality) in enumerate(specs)
    ]


def candidates_of(*specs, temp_c=18.0, occasion="casual"):
    return select(taxo_wardrobe(*specs), temp_c=temp_c, occasion=occasion, rng_seed=SEED)


class TestCategoryMetadata:
    def test_every_category_maps_to_a_supported_slot(self):
        slots = set(SLOT_CATEGORIES)
        for category in CATEGORIES:
            assert CATEGORY_SLOT[category] in slots

    def test_spec_slot_lists(self):
        assert set(SLOT_CATEGORIES["top"]) == {
            "t_shirt", "shirt", "blouse", "polo", "tank_top", "vest",
            "sweater", "cardigan", "hoodie", "sweatshirt", "other_top",
            "dress", "jumpsuit", "romper",
        }
        assert set(SLOT_CATEGORIES["bottom"]) == {
            "jeans", "trousers", "chinos", "skirt", "shorts", "leggings",
            "joggers", "tights", "thermal_leggings", "other_bottom",
        }
        assert set(SLOT_CATEGORIES["shoes"]) == {
            "sneakers", "boots", "loafers", "derbies", "heels", "flats",
            "sandals", "other_shoes",
        }
        assert set(SLOT_CATEGORIES["outerwear"]) == {
            "denim_jacket", "bomber_jacket", "blazer", "trench_coat",
            "coat", "puffer_jacket", "rain_jacket", "other_outerwear",
        }
        assert set(SLOT_CATEGORIES["accessory"]) == {
            "belt", "scarf", "hat", "cap", "beanie", "watch", "bag",
            "jewellery", "other_accessory",
        }

    def test_roles(self):
        # The spec's explicit pins.
        assert CATEGORY_ROLE["vest"] == ROLE_PRIMARY_UPPER
        assert CATEGORY_ROLE["cardigan"] == ROLE_LAYER_UPPER
        for category in ("tights", "leggings", "thermal_leggings"):
            assert CATEGORY_ROLE[category] == ROLE_LOWER_UNDERLAYER
        for category in ("dress", "jumpsuit", "romper"):
            assert CATEGORY_ROLE[category] == ROLE_ONE_PIECE
            # One-pieces persist in the top slot for compatibility.
            assert CATEGORY_SLOT[category] == "top"
        assert CATEGORY_ROLE["jeans"] == ROLE_PRIMARY_LOWER
        assert CATEGORY_ROLE["skirt"] == ROLE_PRIMARY_LOWER
        assert CATEGORY_ROLE["sneakers"] == "footwear"
        assert CATEGORY_ROLE["trench_coat"] == "outerwear"
        assert CATEGORY_ROLE["scarf"] == "accessory"
        # Pullovers are primary tops, not layers.
        for category in ("sweater", "hoodie", "sweatshirt"):
            assert CATEGORY_ROLE[category] == ROLE_PRIMARY_UPPER

    def test_default_category_per_slot(self):
        for slot in SLOT_CATEGORIES:
            assert CATEGORY_SLOT[default_category(slot)] == slot

    def test_item_role_defaults_legacy_rows(self):
        legacy = {"type": "bottom", "warmth": 2, "formality": 2}  # no category key
        assert item_role(legacy) == ROLE_PRIMARY_LOWER


class TestApiCategoryValidation:
    def test_create_with_category_only_derives_type(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Navy linen shirt", "category": "shirt",
            "warmth": 2, "formality": 3,
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["category"] == "shirt"
        assert body["type"] == "top"  # derived server-side

    def test_create_with_matching_pair(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Skirt", "category": "skirt", "type": "bottom",
            "warmth": 2, "formality": 3,
        })
        assert r.status_code == 201
        assert r.json()["type"] == "bottom"

    def test_create_mismatched_pair_rejected(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Jeans", "category": "jeans", "type": "top",
            "warmth": 2, "formality": 2,
        })
        assert r.status_code == 422
        assert "belongs to type" in r.json()["detail"][0]["msg"]

    def test_create_unknown_category_rejected(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Odd", "category": "spacesuit", "warmth": 2, "formality": 2,
        })
        assert r.status_code == 422

    def test_create_without_category_rejected(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Tee", "type": "top", "warmth": 2, "formality": 2,
        })
        assert r.status_code == 422

    def test_one_piece_persists_with_top_slot(self, api):
        client, _ = api
        r = client.post("/api/items", json={
            "name": "Midi dress", "category": "dress", "warmth": 2, "formality": 3,
        })
        assert r.status_code == 201
        assert r.json()["type"] == "top"
        assert r.json()["category"] == "dress"

    def test_update_category_and_mismatch(self, api):
        client, _ = api
        item = client.post("/api/items", json={
            "name": "Tee", "category": "t_shirt", "warmth": 2, "formality": 2,
        }).json()
        r = client.put(f"/api/items/{item['id']}", json={
            "name": "Tee", "category": "polo", "warmth": 2, "formality": 2,
        })
        assert r.status_code == 200
        assert r.json()["category"] == "polo"

        r = client.put(f"/api/items/{item['id']}", json={
            "name": "Tee", "category": "jeans", "type": "top",
            "warmth": 2, "formality": 2,
        })
        assert r.status_code == 422

    def test_list_and_detail_expose_category(self, api):
        client, _ = api
        created = client.post("/api/items", json={
            "name": "Boots", "category": "boots", "warmth": 4, "formality": 3,
        }).json()
        listed = client.get("/api/items").json()["items"]
        assert [i["category"] for i in listed] == ["boots"]
        assert client.get(f"/api/items/{created['id']}").json()["category"] == "boots"

    def test_sort_by_category(self, api):
        client, _ = api
        for name, category in [("B", "skirt"), ("A", "jeans"), ("C", "boots")]:
            client.post("/api/items", json={
                "name": name, "category": category, "warmth": 2, "formality": 2,
            })
        body = client.get("/api/items?sort=category&order=asc").json()
        assert [i["category"] for i in body["items"]] == ["boots", "jeans", "skirt"]

    def test_legacy_row_reads_as_catch_all_category(self, api):
        """A row written without a category (raw SQL, pre-backfill) reads
        as other_<type> everywhere instead of surfacing NULL."""
        client, app = api
        from app.db import connect

        item = client.post("/api/items", json={
            "name": "Tee", "category": "t_shirt", "warmth": 2, "formality": 2,
        }).json()
        conn = connect(app.state.config.db_path)
        conn.execute("UPDATE items SET category = NULL WHERE id = ?", (item["id"],))
        conn.commit()
        conn.close()
        assert client.get(f"/api/items/{item['id']}").json()["category"] == "other_top"


class TestDatabaseBackfill:
    def _raw_db(self, tmp_path):
        import sqlite3

        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL,"
            " type TEXT NOT NULL CHECK (type IN ('top', 'bottom', 'shoes', 'outerwear', 'accessory')),"
            " color TEXT, warmth INTEGER NOT NULL, formality INTEGER NOT NULL,"
            " style_tags TEXT, notes TEXT, times_worn INTEGER NOT NULL DEFAULT 0,"
            " created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
        )
        conn.execute(
            "INSERT INTO items (name, type, warmth, formality) VALUES"
            " ('Old tee', 'top', 2, 2), ('Old jeans', 'bottom', 2, 2),"
            " ('Old boots', 'shoes', 3, 3)"
        )
        conn.commit()
        conn.close()
        return db_path

    def test_backfill_gives_other_type_category(self, tmp_path):
        import sqlite3

        db_path = self._raw_db(tmp_path)
        init_db(db_path)  # adds the column and backfills
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = {r["name"]: r["category"] for r in conn.execute("SELECT * FROM items")}
        conn.close()
        assert rows == {
            "Old tee": "other_top",
            "Old jeans": "other_bottom",
            "Old boots": "other_shoes",
        }

    def test_backfill_is_idempotent_and_keeps_precise_categories(self, tmp_path):
        import sqlite3

        db_path = self._raw_db(tmp_path)
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE items SET category = 't_shirt' WHERE name = 'Old tee'"
        )
        conn.commit()
        conn.close()
        init_db(db_path)
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = {r["name"]: r["category"] for r in conn.execute("SELECT * FROM items")}
        conn.close()
        assert rows["Old tee"] == "t_shirt"  # refined value survives re-runs
        assert rows["Old jeans"] == "other_bottom"


class TestClassifyCategory:
    BASE = {
        "name": "Navy linen shirt",
        "category": "shirt",
        "color": "navy",
        "warmth": 1,
        "formality": 3,
        "style_tags": "summer",
    }

    def test_valid_draft_type_derived(self):
        draft = classify._validate(dict(self.BASE))
        assert draft.category == "shirt"
        assert draft.type == "top"

    def test_matching_type_claim_accepted(self):
        draft = classify._validate({**self.BASE, "type": "top"})
        assert draft.type == "top"

    def test_mismatched_pair_rejected(self):
        with pytest.raises(ValueError):
            classify._validate({**self.BASE, "type": "bottom"})

    def test_unknown_category_rejected(self):
        with pytest.raises(ValueError):
            classify._validate({**self.BASE, "category": "spacesuit"})

    def test_missing_category_rejected(self):
        raw = dict(self.BASE)
        raw.pop("category")
        with pytest.raises(ValueError):
            classify._validate(raw)

    def test_multi_reply_keeps_valid_elements_drops_bad_category(self):
        from conftest import ScriptedProvider

        bad = {**self.BASE, "category": "hat-stand"}
        provider = ScriptedProvider([json.dumps([bad, dict(self.BASE)])])
        drafts = classify.classify_multi(provider, "gemma3:4b", "aGVsbG8=")
        assert [d.category for d in drafts] == ["shirt"]

    def test_prompt_lists_supported_categories(self):
        from conftest import ScriptedProvider

        provider = ScriptedProvider([json.dumps(self.BASE)])
        classify.classify_multi(provider, "gemma3:4b", "aGVsbG8=")
        user_text = provider.calls[0][1]["content"]
        for category in ("t_shirt", "dress", "tights", "trench_coat", "jewellery"):
            assert category in user_text
        assert "one-piece" in user_text


class TestStylistRoleValidation:
    def _reply(self, **item_ids):
        return {
            "title": "t",
            "item_ids": {"accessories": [], **item_ids},
            "rationale": "r",
        }

    def test_cardigan_as_layer_over_primary_top(self):
        cs = candidates_of(
            ("top", "t_shirt", 2, 2), ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        parsed = stylist._validate(
            self._reply(top=1, layer=2, bottom=3, shoes=4), cs
        )
        assert parsed["picks"] == {"top": 1, "layer": 2, "bottom": 3, "shoes": 4}

    def test_cardigan_cannot_be_the_top(self):
        cs = candidates_of(
            ("top", "t_shirt", 2, 2), ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        with pytest.raises(ValueError, match="layer"):
            stylist._validate(self._reply(top=2, bottom=3, shoes=4), cs)

    def test_vest_cannot_pair_with_blouse_via_layer(self):
        # Both are primary uppers: exactly one may be picked, and the
        # other cannot sneak in through 'layer'.
        cs = candidates_of(
            ("top", "vest", 2, 2), ("top", "blouse", 2, 2),
            ("bottom", "skirt", 2, 2), ("shoes", "flats", 2, 2),
        )
        with pytest.raises(ValueError, match="layer"):
            stylist._validate(self._reply(top=1, layer=2, bottom=3, shoes=4), cs)

    def test_one_piece_replaces_bottom(self):
        cs = candidates_of(
            ("top", "dress", 2, 3), ("shoes", "flats", 2, 3),
        )
        parsed = stylist._validate(self._reply(top=1, shoes=2), cs)
        assert "bottom" not in parsed["picks"]

    def test_one_piece_with_bottom_rejected(self):
        cs = candidates_of(
            ("top", "dress", 2, 3), ("bottom", "skirt", 2, 3),
            ("shoes", "flats", 2, 3),
        )
        with pytest.raises(ValueError, match="one-piece"):
            stylist._validate(self._reply(top=1, bottom=2, shoes=3), cs)

    def test_tights_under_skirt_accepted(self):
        cs = candidates_of(
            ("top", "sweater", 2, 2), ("bottom", "skirt", 2, 2),
            ("bottom", "tights", 2, 2), ("shoes", "boots", 2, 2),
        )
        parsed = stylist._validate(
            self._reply(top=1, bottom=2, underlayer=3, shoes=4), cs
        )
        assert parsed["picks"]["underlayer"] == 3

    def test_tights_under_jeans_rejected(self):
        cs = candidates_of(
            ("top", "sweater", 2, 2), ("bottom", "jeans", 2, 2),
            ("bottom", "tights", 2, 2), ("shoes", "boots", 2, 2),
        )
        with pytest.raises(ValueError, match="skirt, dress"):
            stylist._validate(
                self._reply(top=1, bottom=2, underlayer=3, shoes=4), cs
            )

    def test_tights_cannot_be_the_bottom(self):
        cs = candidates_of(
            ("top", "sweater", 2, 2), ("bottom", "skirt", 2, 2),
            ("bottom", "tights", 2, 2), ("shoes", "boots", 2, 2),
        )
        with pytest.raises(ValueError, match="underlayer"):
            stylist._validate(self._reply(top=1, bottom=3, shoes=4), cs)

    def test_choose_retries_on_role_violation_then_accepts_fix(self):
        cs = candidates_of(
            ("top", "vest", 2, 2), ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        bad = json.dumps(self._reply(top=2, bottom=3, shoes=4))  # cardigan as top
        good = json.dumps(self._reply(top=1, layer=2, bottom=3, shoes=4))
        provider = ScriptedProvider([bad, good])
        choice = stylist.choose(provider, "m", cs, "chill", "casual")
        assert choice.source == "llm"
        assert choice.slot_picks["layer"] == 2


class TestFallbackRoles:
    def test_dress_only_wardrobe_produces_one_piece_without_bottom(self):
        cs = candidates_of(("top", "dress", 2, 3), ("shoes", "flats", 2, 3))
        choice = stylist.fallback_choice(cs)
        assert choice.slot_picks["top"] == 1
        assert "bottom" not in choice.slot_picks
        assert choice.slot_picks["shoes"] == 2

    def test_never_returns_competing_primary_uppers(self):
        cs = candidates_of(
            ("top", "vest", 2, 2), ("top", "blouse", 2, 2),
            ("bottom", "skirt", 2, 2), ("shoes", "flats", 2, 2),
        )
        choice = stylist.fallback_choice(cs)
        top_roles = [
            it["role"] for it in cs.slots["top"] if it["id"] in choice.slot_picks.values()
        ]
        uppers = [r for r in top_roles if r == ROLE_PRIMARY_UPPER]
        assert len(uppers) == 1

    def test_fallback_adds_cardigan_layer(self):
        cs = candidates_of(
            ("top", "t_shirt", 2, 2), ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        choice = stylist.fallback_choice(cs)
        assert choice.slot_picks["layer"] == 2

    def test_fallback_adds_tights_under_skirt(self):
        cs = candidates_of(
            ("top", "sweater", 4, 2), ("bottom", "skirt", 4, 2),
            ("bottom", "tights", 4, 2), ("shoes", "boots", 4, 2),
            temp_c=5.0,
        )
        choice = stylist.fallback_choice(cs)
        assert choice.slot_picks["bottom"] == 2
        assert choice.slot_picks["underlayer"] == 3

    def test_fallback_never_adds_tights_under_jeans(self):
        cs = candidates_of(
            ("top", "sweater", 4, 2), ("bottom", "jeans", 4, 2),
            ("bottom", "tights", 4, 2), ("shoes", "boots", 4, 2),
            temp_c=5.0,
        )
        choice = stylist.fallback_choice(cs)
        assert "underlayer" not in choice.slot_picks

    def test_fallback_skips_layer_when_only_top_is_one_piece(self):
        # A dress is the only upper garment: one-piece outfit, and the
        # cardigan still layers over it.
        cs = candidates_of(
            ("top", "dress", 2, 3), ("top", "cardigan", 2, 2),
            ("shoes", "flats", 2, 3),
        )
        choice = stylist.fallback_choice(cs)
        assert "bottom" not in choice.slot_picks
        assert choice.slot_picks["layer"] == 2

    def test_fallback_avoid_rotates_layer_too(self):
        cs = candidates_of(
            ("top", "t_shirt", 2, 2), ("top", "cardigan", 2, 2),
            ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        cardigan_ids = sorted(it["id"] for it in cs.layer_upper)
        assert len(cardigan_ids) == 2
        choice = stylist.fallback_choice(cs, avoid={cardigan_ids[0]})
        assert choice.slot_picks["layer"] == cardigan_ids[1]


class TestCandidateRoles:
    def test_only_cardigan_tops_are_incomplete(self):
        cs = candidates_of(
            ("top", "cardigan", 2, 2),
            ("bottom", "jeans", 2, 2), ("shoes", "sneakers", 2, 2),
        )
        assert not cs.has_required
        assert any("primary top" in g for g in cs.gaps)

    def test_dress_covers_upper_and_lower(self):
        cs = candidates_of(("top", "dress", 2, 3), ("shoes", "flats", 2, 3))
        assert cs.has_required

    def test_only_tights_bottoms_are_incomplete(self):
        cs = candidates_of(
            ("top", "sweater", 2, 2), ("bottom", "tights", 2, 2),
            ("shoes", "boots", 2, 2),
        )
        assert not cs.has_required
        assert any("primary bottom" in g for g in cs.gaps)

    def test_skirt_plus_tights_is_complete(self):
        cs = candidates_of(
            ("top", "sweater", 2, 2), ("bottom", "skirt", 2, 2),
            ("bottom", "tights", 2, 2), ("shoes", "boots", 2, 2),
        )
        assert cs.has_required
        assert cs.primary_lower[0]["category"] == "skirt"
        assert cs.lower_underlayer[0]["category"] == "tights"

    def test_candidates_carry_category_and_role(self):
        cs = candidates_of(
            ("top", "vest", 2, 2), ("bottom", "jeans", 2, 2),
            ("shoes", "sneakers", 2, 2),
        )
        assert cs.primary_upper[0]["category"] == "vest"
        assert cs.primary_upper[0]["role"] == ROLE_PRIMARY_UPPER


class TestRecommendRoleFlow:
    def _service(self, conn, provider):
        from app.config import AppConfig

        svc = RecommendationService()
        svc.provider_for = lambda url: provider
        return svc, AppConfig(db_path="unused")

    def _seed(self, conn, specs):
        for name, type_, category, warmth, formality in specs:
            conn.execute(
                "INSERT INTO items (name, type, category, warmth, formality, style_tags)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (name, type_, category, warmth, formality, None),
            )

    def test_llm_outfit_includes_layer_and_underlayer(self, conn):
        self._seed(conn, [
            ("Vest", "top", "vest", 2, 2), ("Cardigan", "top", "cardigan", 2, 2),
            ("Skirt", "bottom", "skirt", 2, 2), ("Tights", "bottom", "tights", 2, 2),
            ("Sneakers", "shoes", "sneakers", 2, 2),
        ])
        cs = select(
            [dict(r) for r in conn.execute("SELECT * FROM items")],
            18.0, "casual", SEED,
        )
        reply = json.dumps({
            "title": "Layered skirt look",
            "item_ids": {
                "top": 1, "layer": 2, "bottom": 3, "underlayer": 4, "shoes": 5,
            },
            "rationale": "r",
        })
        svc, cfg = self._service(conn, ScriptedProvider([reply]))
        resp = svc.recommend(
            conn=conn, config=cfg, city="Paris", model="m",
            ollama_url="http://x", weather_service=FakeWeatherService(18.0),
            mood="chill", occasion="casual", rng_seed=SEED,
        )
        pieces = {(oi.item.name, oi.slot) for oi in resp.outfit}
        assert ("Cardigan", "top") in pieces  # layered over the vest
        assert ("Tights", "bottom") in pieces  # under the skirt
        assert ("Skirt", "bottom") in pieces
        assert len(resp.outfit) == 5

    def test_fallback_one_piece_outfit(self, conn):
        self._seed(conn, [
            ("Midi dress", "top", "dress", 2, 3), ("Flats", "shoes", "flats", 2, 3),
        ])
        svc, cfg = self._service(conn, ScriptedProvider([]))
        resp = svc.recommend(
            conn=conn, config=cfg, city="Paris", model="m",
            ollama_url="http://x", weather_service=FakeWeatherService(18.0),
            mood="chill", occasion="casual", rng_seed=SEED,
        )
        assert resp.source == "fallback"
        slots = [oi.slot for oi in resp.outfit]
        assert "top" in slots and "bottom" not in slots
        assert resp.outfit[0].item.category == "dress"

    def test_incomplete_wardrobe_reports_role_gap(self, conn):
        self._seed(conn, [
            ("Cardigan", "top", "cardigan", 2, 2),
            ("Jeans", "bottom", "jeans", 2, 2),
            ("Sneakers", "shoes", "sneakers", 2, 2),
        ])
        svc, cfg = self._service(conn, ScriptedProvider([]))
        resp = svc.recommend(
            conn=conn, config=cfg, city="Paris", model="m",
            ollama_url="http://x", weather_service=FakeWeatherService(18.0),
            mood="chill", occasion="casual", rng_seed=SEED,
        )
        assert resp.outfit == []
        assert any("primary top" in g for g in resp.gaps)
