"""CandidateSelector: deterministic pre-filter that narrows the wardrobe.

This is the engine's rule-based half. Weather picks a warmth band, the
occasion picks a formality band, and every clothing slot must be covered.
Mood is deliberately NOT used here — judging mood is the LLM's job.

Typical result: 100-300 items -> ~20 candidates, small enough for a
small local model to reason over.

Candidates stay grouped by BROAD slot (top/bottom/shoes/outerwear/
accessory) so the stylist prompt stays compact, but each row also carries
its detailed category and outfit role (derived from the central category
metadata) so the stylist and fallback can enforce the role constraints:
one primary upper (or a one-piece), one primary lower, optional layers
and underlayers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..categories import (
    ROLE_LAYER_UPPER,
    ROLE_LOWER_UNDERLAYER,
    ROLE_ONE_PIECE,
    ROLE_PRIMARY_LOWER,
    ROLE_PRIMARY_UPPER,
    item_category,
    item_role,
)
REQUIRED_SLOTS = ("top", "bottom", "shoes")
# Optional slots: outerwear only offered when cold, accessories weather-aware.
OPTIONAL_SLOTS = ("outerwear", "accessory")
CAP_REQUIRED = 8   # max candidates shown to the LLM per required slot
CAP_OPTIONAL = 4
OUTERWEAR_MAX_TEMP_C = 14.0  # outerwear only offered below this

# temperature (C) -> allowed warmth range (inclusive)
WARMTH_BANDS = [
    (24.0, (1, 1)),
    (17.0, (1, 2)),
    (10.0, (2, 3)),
    (4.0, (3, 4)),
    (float("-inf"), (4, 5)),
]

# occasion -> allowed formality range (inclusive)
FORMALITY_BANDS = {
    "gym": (1, 3),
    "casual": (1, 3),
    "work": (2, 4),
    "smart": (3, 5),
    "formal": (4, 5),
}

# occasion -> where the LLM/fallback should aim (floor + 1, capped at 5)
FORMALITY_TARGET = {
    "gym": 1,
    "casual": 2,
    "work": 3,
    "smart": 4,
    "formal": 5,
}


def warmth_band(temp_c: float) -> tuple[int, int]:
    for threshold, band in WARMTH_BANDS:
        if temp_c >= threshold:
            return band
    return WARMTH_BANDS[-1][1]


@dataclass
class CandidateSet:
    slots: dict[str, list[dict]] = field(default_factory=dict)  # slot -> candidates
    gaps: list[str] = field(default_factory=list)               # human-readable problems
    temp_c: float = 0.0
    occasion: str = "casual"

    # Role-filtered views over the broad slot pools. Every candidate row
    # carries its `category` and `role` (attached by select()).
    def _by_role(self, slot: str, *roles: str) -> list[dict]:
        return [
            it for it in self.slots.get(slot, []) if it.get("role") in roles
        ]

    @property
    def primary_upper(self) -> list[dict]:
        return self._by_role("top", ROLE_PRIMARY_UPPER)

    @property
    def layer_upper(self) -> list[dict]:
        return self._by_role("top", ROLE_LAYER_UPPER)

    @property
    def one_piece(self) -> list[dict]:
        return self._by_role("top", ROLE_ONE_PIECE)

    @property
    def primary_lower(self) -> list[dict]:
        return self._by_role("bottom", ROLE_PRIMARY_LOWER)

    @property
    def lower_underlayer(self) -> list[dict]:
        return self._by_role("bottom", ROLE_LOWER_UNDERLAYER)

    @property
    def has_required(self) -> bool:
        """A complete outfit is possible: footwear, an upper garment
        (primary top or one-piece), and — unless a one-piece covers it —
        a primary lower. A layer (cardigan) or underlayer (tights) can
        never replace either."""
        if not self.slots.get("shoes"):
            return False
        if not (self.primary_upper or self.one_piece):
            return False
        if self.one_piece:
            return True
        return bool(self.primary_lower)


def _with_role(it: dict) -> dict:
    """Attach the item's category and outfit role (idempotent)."""
    category = item_category(it)
    return {**it, "category": category, "role": item_role(it)}


def select(
    items: list[dict],
    temp_c: float,
    occasion: str,
    rng_seed: int,
    activity: str | None = None,
) -> CandidateSet:
    """Filter wardrobe items into per-slot candidate lists.

    rng_seed: date-derived so results vary day-to-day but are stable
    within a day (and reproducible in tests).

    activity: free text about what the person will be doing ("Christmas
    dinner", "zoo day"). When stated, a warm-layer option is guaranteed:
    layer pieces matching the occasion's formality are offered even when
    the day's warmth band would exclude them.
    """
    w_lo, w_hi = warmth_band(temp_c)
    f_lo, f_hi = FORMALITY_BANDS.get(occasion, FORMALITY_BANDS["casual"])
    rng = random.Random(rng_seed)

    result = CandidateSet(temp_c=temp_c, occasion=occasion)

    def filter_slot(slot: str, w_range: tuple[int, int]) -> list[dict]:
        lo, hi = w_range
        return [
            _with_role(it) for it in items
            if it["type"] == slot and lo <= it["warmth"] <= hi and f_lo <= it["formality"] <= f_hi
        ]

    def fill(slot: str, cap: int, relax_until_found: bool) -> None:
        candidates = filter_slot(slot, (w_lo, w_hi))
        if not candidates and relax_until_found:
            # Progressively widen the warmth band until something fits: a
            # wardrobe with no ideal-temperature items still yields an
            # outfit, with a note telling the user it's a stretch.
            for step in range(1, 5):
                lo, hi = max(1, w_lo - step), min(5, w_hi + step)
                candidates = filter_slot(slot, (lo, hi))
                if candidates:
                    if (lo, hi) != (1, 5):  # a genuine stretch, not an empty band
                        result.gaps.append(
                            f"Note: no {slot} in the ideal warmth band for "
                            f"{temp_c:.0f}°C; closest matches were relaxed in."
                        )
                    break
        if len(candidates) > cap:
            candidates = sorted(candidates, key=lambda it: it["id"])
            candidates = rng.sample(candidates, cap)
        result.slots[slot] = candidates

    for slot in REQUIRED_SLOTS:
        fill(slot, CAP_REQUIRED, relax_until_found=True)

    # Role-aware completeness: a filled slot is not enough — the outfit
    # needs a primary upper (or a one-piece) and a primary lower. Layers
    # (cardigan) and underlayers (tights) cannot replace either.
    if not result.slots["top"]:
        result.gaps.append(
            f"No top in your wardrobe fits {occasion} wear at {temp_c:.0f}°C "
            f"(need warmth {w_lo}-{w_hi}, formality {f_lo}-{f_hi}). "
            f"Add one, or relax your filters."
        )
    elif not result.primary_upper and not result.one_piece:
        result.gaps.append(
            f"No primary top (e.g. shirt, tee, sweater, dress) fits {occasion} "
            f"wear at {temp_c:.0f}°C — only layer pieces like cardigans "
            f"matched, and a layer cannot replace the top."
        )
    if not result.slots["bottom"]:
        result.gaps.append(
            f"No bottom in your wardrobe fits {occasion} wear at {temp_c:.0f}°C "
            f"(need warmth {w_lo}-{w_hi}, formality {f_lo}-{f_hi}). "
            f"Add one, or relax your filters."
        )
    elif not result.one_piece and not result.primary_lower:
        result.gaps.append(
            f"No primary bottom (e.g. jeans, trousers, skirt, shorts) fits "
            f"{occasion} wear at {temp_c:.0f}°C — only underlayers like "
            f"tights matched, and an underlayer cannot replace the bottom."
        )
    if not result.slots["shoes"]:
        result.gaps.append(
            f"No shoes in your wardrobe fits {occasion} wear at {temp_c:.0f}°C "
            f"(need warmth {w_lo}-{w_hi}, formality {f_lo}-{f_hi}). "
            f"Add one, or relax your filters."
        )

    # A stated activity guarantees a warm-layer option: dinners, weddings
    # and other events want a cardigan even on a mild day, so offer layer
    # pieces that match the occasion's formality regardless of warmth.
    if activity and not result.layer_upper:
        extras = [
            _with_role(it) for it in items
            if it["type"] == "top"
            and item_role(it) == ROLE_LAYER_UPPER
            and f_lo <= it["formality"] <= f_hi
        ]
        # Closest warmth to the day's band first, id as tie-break: the
        # offered layer is as weather-sensible as the wardrobe allows.
        extras.sort(key=lambda it: (abs(it["warmth"] - (w_lo + w_hi) / 2), it["id"]))
        result.slots["top"].extend(extras[:2])

    # Optional slots: outerwear only when cold, accessories when any exist.
    if temp_c < OUTERWEAR_MAX_TEMP_C:
        fill("outerwear", CAP_OPTIONAL, relax_until_found=True)
    # Accessories are weather-aware like every other slot: offer the
    # warmth-band matches first, and only relax to the full range when the
    # band pool is empty (a wool beanie shouldn't be offered on a 30°C day
    # when a warmth-1 watch was available).
    fill("accessory", CAP_OPTIONAL, relax_until_found=True)

    return result
