"""Seed a broad, varied wardrobe so the app is testable instantly.

Usage: .venv/bin/python scripts/seed_wardrobe.py [--db data/llm_style.db]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The catalog deliberately has an uneven type mix: a typical wardrobe has
# more tops and bottoms than shoes, outerwear, or accessories. Each product
# is paired with every style profile, producing 500 distinct seed items.
# Every product carries its precise CATEGORY (the broad type is derived
# from it by the app); one-pieces (dress) sit in the top slot.
STYLE_PROFILES = [
    ("Minimal", "minimal, clean, modern", 0, 0),
    ("Classic", "classic, timeless, versatile", 0, 1),
    ("Streetwear", "streetwear, urban, relaxed", 0, -1),
    ("Preppy", "preppy, polished, collegiate", 0, 1),
    ("Sport", "sport, performance, active", -1, -2),
    ("Workwear", "workwear, durable, utility", 1, -1),
    ("Bohemian", "bohemian, textured, expressive", 0, 0),
    ("Scandinavian", "scandinavian, neutral, understated", 1, 0),
    ("Vintage", "vintage, retro, characterful", 0, 0),
    ("Tailored", "tailored, refined, smart", 0, 1),
]

COLORS = [
    "white", "black", "navy", "charcoal", "cream", "olive", "camel",
    "burgundy", "indigo", "light blue",
]

# type -> [(item name, category, baseline warmth, baseline formality, tags)]
CATEGORY_CATALOG = {
    "top": [
        ("Crew Tee", "t_shirt", 1, 1, "basics"),
        ("Oxford Shirt", "shirt", 2, 3, "button-down"),
        ("Linen Shirt", "shirt", 1, 3, "summer"),
        ("Merino Jumper", "sweater", 3, 3, "knitwear"),
        ("Turtleneck", "sweater", 3, 4, "knitwear"),
        ("Polo Shirt", "polo", 1, 2, "smart-casual"),
        ("Hoodie", "hoodie", 3, 1, "layering"),
        ("Henley", "shirt", 2, 2, "casual"),
        ("Camp Collar Shirt", "shirt", 1, 2, "summer"),
        ("Flannel Shirt", "shirt", 3, 2, "autumn"),
        ("Rugby Shirt", "polo", 2, 2, "casual"),
        ("Cardigan", "cardigan", 3, 3, "layering"),
        ("Midi Dress", "dress", 2, 3, "one-piece"),
        ("Sweatshirt", "sweatshirt", 3, 1, "casual"),
        ("Silk Blouse", "blouse", 1, 4, "dressy"),
        ("Technical Tee", "t_shirt", 1, 1, "performance"),
    ],
    "bottom": [
        ("Straight Jeans", "jeans", 2, 2, "denim"),
        ("Wide-Leg Trousers", "trousers", 2, 3, "smart-casual"),
        ("Chinos", "chinos", 2, 3, "versatile"),
        ("Wool Trousers", "trousers", 3, 4, "work"),
        ("Tailored Shorts", "shorts", 1, 3, "summer"),
        ("Cargo Pants", "trousers", 2, 1, "utility"),
        ("Opaque Tights", "tights", 4, 2, "layering"),
        ("Joggers", "joggers", 3, 1, "comfort"),
        ("Linen Trousers", "trousers", 1, 3, "summer"),
        ("Thermal Leggings", "thermal_leggings", 4, 1, "winter"),
        ("Corduroy Trousers", "trousers", 3, 2, "autumn"),
        ("Running Shorts", "shorts", 1, 1, "performance"),
        ("Midi Skirt", "skirt", 2, 3, "versatile"),
    ],
    "shoes": [
        ("Leather Sneakers", "sneakers", 2, 2, "everyday"),
        ("Running Shoes", "sneakers", 1, 1, "performance"),
        ("Chelsea Boots", "boots", 4, 3, "autumn"),
        ("Derby Shoes", "derbies", 2, 5, "formal"),
        ("Loafers", "loafers", 1, 4, "smart"),
        ("Court Heels", "heels", 1, 4, "dressy"),
        ("Hiking Boots", "boots", 5, 2, "outdoor"),
        ("Ballet Flats", "flats", 1, 3, "versatile"),
        ("Strappy Sandals", "sandals", 1, 3, "summer"),
    ],
    "outerwear": [
        ("Denim Jacket", "denim_jacket", 3, 2, "layering"),
        ("Trench Coat", "trench_coat", 4, 4, "classic"),
        ("Wool Overcoat", "coat", 5, 4, "winter"),
        ("Puffer Jacket", "puffer_jacket", 5, 1, "winter"),
        ("Bomber Jacket", "bomber_jacket", 3, 2, "casual"),
        ("Blazer", "blazer", 2, 4, "tailoring"),
        ("Rain Shell", "rain_jacket", 2, 2, "weatherproof"),
    ],
    "accessory": [
        ("Leather Belt", "belt", 1, 3, "finishing-touch"),
        ("Wool Scarf", "scarf", 4, 2, "winter"),
        ("Baseball Cap", "cap", 1, 1, "casual"),
        ("Leather Watch", "watch", 1, 4, "classic"),
        ("Beanie", "beanie", 4, 1, "winter"),
    ],
}

CATEGORY_COUNTS = {
    category: len(products) * len(STYLE_PROFILES)
    for category, products in CATEGORY_CATALOG.items()
}

# The catalog is split between TWO seeded personas so pair recommendations
# work out of the box. Style profiles alternate between the two wardrobes:
# each persona gets every product (and therefore every category) five times,
# 250 items each.
SECOND_PERSONA_ID = 2
SECOND_PERSONA_NAME = "Partner"

# Genders for the seeded household so the stylist's silhouette guidance
# works out of the box (both are editable in Settings afterwards).
FIRST_PERSONA_GENDER = "male"
SECOND_PERSONA_GENDER = "female"


def persona_for_profile(style_index: int) -> int:
    return 1 if style_index % 2 == 0 else SECOND_PERSONA_ID


def _clamp(value: int) -> int:
    return max(1, min(5, value))


def build_sample_wardrobe() -> list[tuple[str, str, str, str, int, int, str, int]]:
    """Build the ordered 500-item catalog used by the seed script and bench.

    Tuples: (name, type, category, color, warmth, formality, style_tags,
    persona_id)."""
    items = []
    color_index = 0
    # Dict insertion order intentionally puts the types in wardrobe order.
    for type_, products in CATEGORY_CATALOG.items():
        for product, category, base_warmth, base_formality, product_tags in products:
            for style_index, (style, style_tags, warmth_adjustment, formality_adjustment) in enumerate(STYLE_PROFILES):
                color = COLORS[color_index % len(COLORS)]
                color_index += 1
                items.append((
                    f"{style} {color.title()} {product}",
                    type_,
                    category,
                    color,
                    _clamp(base_warmth + warmth_adjustment),
                    _clamp(base_formality + formality_adjustment),
                    f"{style_tags}, {product_tags}",
                    persona_for_profile(style_index),
                ))
    return items


# name, type, category, color, warmth, formality, style_tags
SAMPLE_WARDROBE = build_sample_wardrobe()
assert len(SAMPLE_WARDROBE) == 500
assert CATEGORY_COUNTS == {
    "top": 160, "bottom": 130, "shoes": 90, "outerwear": 70, "accessory": 50,
}


def category_distribution() -> dict[str, int]:
    """Precise-category counts across the 500 seeded items."""
    counts: dict[str, int] = {}
    for _, _, category, *_ in SAMPLE_WARDROBE:
        counts[category] = counts.get(category, 0) + 1
    return counts

assert sum(category_distribution().values()) == 500

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.categories import CATEGORY_SLOT  # noqa: E402

# Every seeded category must be a supported one for its broad type.
assert all(
    CATEGORY_SLOT.get(category) == type_
    for _, type_, category, *_ in SAMPLE_WARDROBE
), "seed catalog contains an invalid type/category pair"


def seed(conn) -> bool:
    """Create the second persona, set both personas' genders, and insert
    the 500-item catalog. Returns False (and changes nothing) when the
    items table already has rows — seeding never duplicates."""
    existing = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
    if existing:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO personas (id, name) VALUES (?, ?)",
        (SECOND_PERSONA_ID, SECOND_PERSONA_NAME),
    )
    conn.execute(
        "UPDATE personas SET gender = ? WHERE id = 1", (FIRST_PERSONA_GENDER,)
    )
    conn.execute(
        "UPDATE personas SET gender = ? WHERE id = ?",
        (SECOND_PERSONA_GENDER, SECOND_PERSONA_ID),
    )
    conn.executemany(
        "INSERT INTO items (name, type, category, color, warmth, formality, style_tags, persona_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        SAMPLE_WARDROBE,
    )
    conn.commit()
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    default_db = Path(__file__).resolve().parents[1] / "data" / "llm_style.db"
    parser.add_argument("--db", type=Path, default=default_db)
    args = parser.parse_args()

    from app.db import connect, init_db  # noqa: E402

    init_db(args.db)
    conn = connect(args.db)
    if not seed(conn):
        existing = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
        print(f"Database already has {existing} items; nothing seeded.")
        return
    print(
        f"Seeded {len(SAMPLE_WARDROBE)} items across {SECOND_PERSONA_ID} personas "
        f"({len(SAMPLE_WARDROBE) // 2} each) into {args.db}"
    )


if __name__ == "__main__":
    main()
