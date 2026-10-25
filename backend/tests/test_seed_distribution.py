"""The 500-item seed wardrobe: every item carries a precise category that
is valid for its broad type, the per-category distribution is stable, and
the catalog is split between the two seeded personas ("Me" and "Partner")
with each wardrobe covering every category (pair mode works out of the box)."""
import importlib.util
from pathlib import Path

from app.categories import CATEGORY_SLOT

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "seed_wardrobe", REPO_ROOT / "scripts" / "seed_wardrobe.py"
)
_seed = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_seed)

EXPECTED_DISTRIBUTION = {
    # top (160)
    "t_shirt": 20, "shirt": 50, "sweater": 20, "polo": 20,
    "hoodie": 10, "cardigan": 10, "dress": 10, "sweatshirt": 10, "blouse": 10,
    # bottom (130)
    "jeans": 10, "trousers": 50, "chinos": 10, "shorts": 20,
    "tights": 10, "joggers": 10, "thermal_leggings": 10, "skirt": 10,
    # shoes (90)
    "sneakers": 20, "boots": 20, "derbies": 10, "loafers": 10,
    "heels": 10, "flats": 10, "sandals": 10,
    # outerwear (70)
    "denim_jacket": 10, "trench_coat": 10, "coat": 10, "puffer_jacket": 10,
    "bomber_jacket": 10, "blazer": 10, "rain_jacket": 10,
    # accessory (50)
    "belt": 10, "scarf": 10, "cap": 10, "watch": 10, "beanie": 10,
}


class TestSeedDistribution:
    def test_500_items(self):
        assert len(_seed.SAMPLE_WARDROBE) == 500

    def test_category_distribution(self):
        assert _seed.category_distribution() == EXPECTED_DISTRIBUTION

    def test_broad_type_counts_unchanged(self):
        counts: dict[str, int] = {}
        for _, type_, *_ in _seed.SAMPLE_WARDROBE:
            counts[type_] = counts.get(type_, 0) + 1
        assert counts == {
            "top": 160, "bottom": 130, "shoes": 90, "outerwear": 70, "accessory": 50,
        }

    def test_every_category_valid_for_its_type(self):
        for name, type_, category, *_ in _seed.SAMPLE_WARDROBE:
            assert CATEGORY_SLOT.get(category) == type_, name

    def test_seed_covers_one_piece_layer_and_underlayer_roles(self):
        categories = {category for _, _, category, *_ in _seed.SAMPLE_WARDROBE}
        assert "dress" in categories       # one-piece
        assert "cardigan" in categories    # layer upper
        assert {"tights", "thermal_leggings"} <= categories  # lower underlayer

    def test_catalog_is_deterministic(self):
        assert _seed.build_sample_wardrobe() == _seed.SAMPLE_WARDROBE


class TestSeedPersonas:
    """The seed outfits TWO personas so pair recommendations demo instantly."""

    def test_items_come_in_two_equal_halves(self):
        counts: dict[int, int] = {}
        for *_, persona in _seed.SAMPLE_WARDROBE:
            counts[persona] = counts.get(persona, 0) + 1
        assert counts == {1: 250, 2: 250}

    def test_second_persona_is_named_partner(self):
        assert _seed.SECOND_PERSONA_ID == 2
        assert _seed.SECOND_PERSONA_NAME == "Partner"
        assert _seed.persona_for_profile(0) == 1
        assert _seed.persona_for_profile(1) == _seed.SECOND_PERSONA_ID

    def test_each_persona_covers_every_seeded_category(self):
        # Every category the catalog contains must exist in BOTH wardrobes
        # (categories without a seed product are simply absent from both).
        catalog_categories = {category for _, _, category, *_ in _seed.SAMPLE_WARDROBE}
        assert len(catalog_categories) == 36  # catalog has no hat/bag/leggings/... products
        for persona in (1, 2):
            covered = {
                category
                for _, _, category, *rest, p in _seed.SAMPLE_WARDROBE
                if p == persona
            }
            assert covered == catalog_categories, f"persona {persona} incomplete"

    def test_each_persona_covers_every_broad_type(self):
        for persona in (1, 2):
            covered = {type_ for _, type_, *_, p in _seed.SAMPLE_WARDROBE if p == persona}
            assert covered == {"top", "bottom", "shoes", "outerwear", "accessory"}, (
                f"persona {persona} incomplete"
            )


class TestSeedPersonaGenders:
    def test_seed_assigns_genders_to_both_personas(self, tmp_path):
        import sqlite3

        from app.db import connect, init_db

        db_path = tmp_path / "seed.db"
        init_db(db_path)
        conn = connect(db_path)
        _seed.seed(conn)
        rows = {
            r["id"]: r["gender"]
            for r in conn.execute("SELECT id, gender FROM personas")
        }
        conn.close()
        assert rows == {1: _seed.FIRST_PERSONA_GENDER, 2: _seed.SECOND_PERSONA_GENDER}
        assert _seed.FIRST_PERSONA_GENDER == "male"
        assert _seed.SECOND_PERSONA_GENDER == "female"

    def test_seed_is_self_guarded_never_duplicates(self, tmp_path):
        import sqlite3

        from app.db import connect, init_db

        db_path = tmp_path / "seed2.db"
        init_db(db_path)
        conn = connect(db_path)
        assert _seed.seed(conn) is True
        assert _seed.seed(conn) is False  # existing items -> no-op
        n = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
        conn.close()
        assert n == 500
