"""Central garment-category metadata: detailed categories, their broad
recommendation slot (the item `type`), and their outfit role.

One source of truth shared by the API validation, the DB backfill, the
candidate selector, the stylist prompt/validation, and the vision
classification prompt — so an item can never be stored (or recommended)
with a category whose slot or role the rest of the engine disagrees on.

Slots (the existing broad `type`): top, bottom, shoes, outerwear,
accessory. One-piece garments (dress, jumpsuit, romper) sit in the `top`
slot for persistence compatibility but carry the `one_piece` role: they
replace both the primary upper and the primary lower in an outfit.
"""
from __future__ import annotations

ROLE_PRIMARY_UPPER = "primary_upper"
ROLE_LAYER_UPPER = "layer_upper"
ROLE_ONE_PIECE = "one_piece"
ROLE_PRIMARY_LOWER = "primary_lower"
ROLE_LOWER_UNDERLAYER = "lower_underlayer"
ROLE_FOOTWEAR = "footwear"
ROLE_OUTERWEAR = "outerwear"
ROLE_ACCESSORY = "accessory"

# Detailed categories per broad slot. Order is stable (prompt display).
SLOT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "top": (
        "t_shirt", "shirt", "blouse", "polo", "tank_top", "vest",
        "sweater", "cardigan", "hoodie", "sweatshirt", "other_top",
        "dress", "jumpsuit", "romper",
    ),
    "bottom": (
        "jeans", "trousers", "chinos", "skirt", "shorts", "leggings",
        "joggers", "tights", "thermal_leggings", "other_bottom",
    ),
    "shoes": (
        "sneakers", "boots", "loafers", "derbies", "heels", "flats",
        "sandals", "other_shoes",
    ),
    "outerwear": (
        "denim_jacket", "bomber_jacket", "blazer", "trench_coat",
        "coat", "puffer_jacket", "rain_jacket", "other_outerwear",
    ),
    "accessory": (
        "belt", "scarf", "hat", "cap", "beanie", "watch", "bag",
        "jewellery", "other_accessory",
    ),
}

# Worn instead of a primary upper + primary lower.
ONE_PIECE_CATEGORIES: tuple[str, ...] = ("dress", "jumpsuit", "romper")

# Optional layer worn OVER the primary upper (never a substitute for it).
LAYER_UPPER_CATEGORIES: tuple[str, ...] = ("cardigan",)

# Optional underlayer worn UNDER a skirt, dress or shorts; never replaces
# a primary lower (tights work under a skirt, not as the bottom itself).
LOWER_UNDERLAYER_CATEGORIES: tuple[str, ...] = (
    "tights", "leggings", "thermal_leggings",
)

# A category that may be paired with a lower underlayer.
UNDERLAYER_HOST_CATEGORIES: tuple[str, ...] = ("skirt", "shorts")

_SLOT_ROLES = {
    "top": ROLE_PRIMARY_UPPER,
    "bottom": ROLE_PRIMARY_LOWER,
    "shoes": ROLE_FOOTWEAR,
    "outerwear": ROLE_OUTERWEAR,
    "accessory": ROLE_ACCESSORY,
}

_ROLE_OVERRIDES = {
    c: ROLE_LAYER_UPPER for c in LAYER_UPPER_CATEGORIES
} | {c: ROLE_ONE_PIECE for c in ONE_PIECE_CATEGORIES} | {
    c: ROLE_LOWER_UNDERLAYER for c in LOWER_UNDERLAYER_CATEGORIES
}

CATEGORY_SLOT: dict[str, str] = {
    category: slot for slot, cats in SLOT_CATEGORIES.items() for category in cats
}
CATEGORY_ROLE: dict[str, str] = {
    category: _ROLE_OVERRIDES.get(category, _SLOT_ROLES[slot])
    for category, slot in CATEGORY_SLOT.items()
}

# All supported categories, stable order (slot list order).
CATEGORIES: tuple[str, ...] = tuple(CATEGORY_SLOT)


def default_category(slot: str) -> str:
    """The compatible category for a row that predates `category`
    (migration backfill): the slot's catch-all."""
    return f"other_{slot}"


def item_category(item: dict) -> str:
    """An item row's effective category, defaulting pre-backfill rows."""
    return item.get("category") or default_category(item["type"])


def item_role(item: dict) -> str:
    """An item row's outfit role, derived from its category."""
    return CATEGORY_ROLE[item_category(item)]


def categories_for_prompt() -> str:
    """Compact grouped listing for the vision-classification prompt."""
    lines = []
    for slot, cats in SLOT_CATEGORIES.items():
        pieces = []
        if slot == "top":
            one_pieces = [c for c in cats if c in ONE_PIECE_CATEGORIES]
            plain = [c for c in cats if c not in ONE_PIECE_CATEGORIES]
            pieces.append(f"top: {', '.join(plain)}")
            if one_pieces:
                pieces.append(f"one-piece (worn instead of top+bottom): {', '.join(one_pieces)}")
        else:
            pieces.append(f"{slot}: {', '.join(cats)}")
        lines.extend(pieces)
    return "\n".join(lines)
