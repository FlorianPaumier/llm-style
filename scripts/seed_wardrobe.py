"""Seed the wardrobe with a realistic sample so the app is testable instantly.

Usage: .venv/bin/python scripts/seed_wardrobe.py [--db data/llm_style.db]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# name, type, color, warmth, formality, style_tags
SAMPLE_WARDROBE = [
    ("White crew tee", "top", "white", 1, 1, "basics, minimal"),
    ("Navy linen shirt", "top", "navy", 1, 3, "summer, smart-casual"),
    ("Striped breton tee", "top", "navy/white", 2, 2, "classic, french"),
    ("Grey hoodie", "top", "grey", 3, 1, "streetwear, cosy"),
    ("Cream knit jumper", "top", "cream", 4, 2, "cosy, soft"),
    ("Oxford shirt", "top", "light blue", 2, 4, "work, preppy"),
    ("Black turtleneck", "top", "black", 3, 4, "minimal, smart"),
    ("Wool overshirt", "top", "olive", 4, 3, "layering, autumn"),
    ("Technical running tee", "top", "black", 1, 1, "gym, sport"),
    ("Denim jacket", "outerwear", "indigo", 3, 2, "classic, casual"),
    ("Beige trench coat", "outerwear", "beige", 4, 4, "classic, smart"),
    ("Puffer jacket", "outerwear", "black", 5, 1, "winter, streetwear"),
    ("Wool overcoat", "outerwear", "charcoal", 5, 4, "winter, formal"),
    ("Blue slim jeans", "bottom", "indigo", 2, 2, "everyday"),
    ("Black straight jeans", "bottom", "black", 2, 2, "minimal"),
    ("Beige chinos", "bottom", "beige", 2, 3, "smart-casual"),
    ("Charcoal wool trousers", "bottom", "charcoal", 3, 4, "work, formal"),
    ("Navy shorts", "bottom", "navy", 1, 1, "summer"),
    ("Running shorts", "bottom", "black", 1, 1, "gym, sport"),
    ("Training joggers", "bottom", "grey", 3, 1, "gym, cosy"),
    ("White sneakers", "shoes", "white", 1, 2, "minimal, everyday"),
    ("Black leather sneakers", "shoes", "black", 2, 3, "smart-casual"),
    ("Brown suede boots", "shoes", "brown", 4, 3, "autumn, smart-casual"),
    ("Black derby shoes", "shoes", "black", 3, 5, "formal"),
    ("Running shoes", "shoes", "white", 1, 1, "gym, sport"),
    ("Winter boots", "shoes", "black", 5, 2, "winter"),
    ("Canvas belt", "accessory", "navy", 1, 3, "basics"),
    ("Wool scarf", "accessory", "grey", 4, 3, "winter, cosy"),
    ("Baseball cap", "accessory", "navy", 1, 1, "streetwear"),
    ("Leather watch", "accessory", "brown", 1, 4, "classic"),
    ("Beanie", "accessory", "black", 4, 1, "winter, casual"),
]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import connect, init_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    default_db = Path(__file__).resolve().parents[1] / "data" / "llm_style.db"
    parser.add_argument("--db", type=Path, default=default_db)
    args = parser.parse_args()

    init_db(args.db)
    conn = connect(args.db)
    existing = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
    if existing:
        print(f"Database already has {existing} items; nothing seeded.")
        return
    conn.executemany(
        "INSERT INTO items (name, type, color, warmth, formality, style_tags)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        SAMPLE_WARDROBE,
    )
    conn.commit()
    print(f"Seeded {len(SAMPLE_WARDROBE)} items into {args.db}")


if __name__ == "__main__":
    main()
