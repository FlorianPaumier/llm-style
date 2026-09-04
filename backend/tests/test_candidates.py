"""Unit tests for the deterministic CandidateSelector."""
from app.services.candidates import (
    CAP_OPTIONAL,
    CAP_REQUIRED,
    OUTERWEAR_MAX_TEMP_C,
    select,
    warmth_band,
)

from conftest import full_wardrobe, make_item

SEED = 20260903


def test_warmth_bands_map_temperature_ranges():
    assert warmth_band(30.0) == (1, 1)
    assert warmth_band(24.0) == (1, 1)
    assert warmth_band(23.9) == (1, 2)
    assert warmth_band(17.0) == (1, 2)
    assert warmth_band(16.9) == (2, 3)
    assert warmth_band(10.0) == (2, 3)
    assert warmth_band(9.9) == (3, 4)
    assert warmth_band(4.0) == (3, 4)
    assert warmth_band(-5.0) == (4, 5)


def test_covers_required_slots_for_mild_casual_day():
    cs = select(full_wardrobe(), temp_c=18.0, occasion="casual", rng_seed=SEED)
    assert cs.has_required
    for slot in ("top", "bottom", "shoes"):
        assert cs.slots[slot], f"{slot} empty"
    # All candidates must satisfy the warmth and formality bands.
    for it in cs.slots["top"]:
        assert 1 <= it["warmth"] <= 2 and 1 <= it["formality"] <= 3


def test_formality_floor_excludes_tees_for_formal_occasion():
    cs = select(full_wardrobe(), temp_c=18.0, occasion="formal", rng_seed=SEED)
    for it in cs.slots["top"]:
        assert it["formality"] >= 4


def test_gym_keeps_athletic_formality_only():
    cs = select(full_wardrobe(), temp_c=18.0, occasion="gym", rng_seed=SEED)
    for slot in ("top", "bottom", "shoes"):
        for it in cs.slots[slot]:
            assert 1 <= it["formality"] <= 3


def test_outerwear_offered_only_when_cold():
    warm = select(full_wardrobe(), temp_c=20.0, occasion="casual", rng_seed=SEED)
    assert "outerwear" not in warm.slots

    cold = select(full_wardrobe(), temp_c=5.0, occasion="casual", rng_seed=SEED)
    assert cold.slots.get("outerwear"), "outerwear expected below 14C"


def test_caps_limit_candidates_per_slot():
    items = full_wardrobe() + [
        make_item(100 + i, "top", 2, 2, name=f"tee-{i}") for i in range(20)
    ]
    cs = select(items, temp_c=18.0, occasion="casual", rng_seed=SEED)
    assert len(cs.slots["top"]) <= CAP_REQUIRED
    assert len(cs.slots.get("accessory", [])) <= CAP_OPTIONAL


def test_relaxed_warmth_fills_gap_and_reports_it():
    # Warm day but wardrobe only has warmth-3+ tops: relaxation should kick in.
    items = [
        make_item(1, "top", 3, 2),
        make_item(2, "bottom", 2, 2),
        make_item(3, "shoes", 2, 2),
    ]
    cs = select(items, temp_c=28.0, occasion="casual", rng_seed=SEED)
    assert cs.has_required
    assert any("relaxed" in g for g in cs.gaps)


def test_missing_required_slot_reports_gap():
    items = [make_item(1, "top", 2, 2), make_item(2, "bottom", 2, 2)]  # no shoes
    cs = select(items, temp_c=18.0, occasion="casual", rng_seed=SEED)
    assert not cs.has_required
    assert any("shoes" in g for g in cs.gaps)


def test_seed_reproducibility_same_day_same_candidates():
    # Oversized pool so the cap forces an actual rng.sample decision.
    items = full_wardrobe() + [
        make_item(200 + i, "top", 2, 2, name=f"tee-{i}") for i in range(30)
    ]
    a = select(items, temp_c=18.0, occasion="work", rng_seed=SEED)
    b = select(items, temp_c=18.0, occasion="work", rng_seed=SEED)
    c = select(items, temp_c=18.0, occasion="work", rng_seed=SEED + 1)
    assert a.slots == b.slots  # same seed -> same candidates
    assert a.slots != c.slots  # different seed -> different sample


def test_occasion_unknown_falls_back_to_casual_band():
    cs = select(full_wardrobe(), temp_c=18.0, occasion="beach", rng_seed=SEED)
    assert cs.has_required
