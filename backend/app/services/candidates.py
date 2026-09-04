"""CandidateSelector: deterministic pre-filter that narrows the wardrobe.

This is the engine's rule-based half. Weather picks a warmth band, the
occasion picks a formality band, and every clothing slot must be covered.
Mood is deliberately NOT used here — judging mood is the LLM's job.

Typical result: 100-300 items -> ~20 candidates, small enough for a
small local model to reason over.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

REQUIRED_SLOTS = ("top", "bottom", "shoes")
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

    @property
    def has_required(self) -> bool:
        return all(self.slots.get(s) for s in REQUIRED_SLOTS)


def select(
    items: list[dict],
    temp_c: float,
    occasion: str,
    rng_seed: int,
) -> CandidateSet:
    """Filter wardrobe items into per-slot candidate lists.

    rng_seed: date-derived so results vary day-to-day but are stable
    within a day (and reproducible in tests).
    """
    w_lo, w_hi = warmth_band(temp_c)
    f_lo, f_hi = FORMALITY_BANDS.get(occasion, FORMALITY_BANDS["casual"])
    rng = random.Random(rng_seed)

    result = CandidateSet(temp_c=temp_c, occasion=occasion)

    def filter_slot(slot: str, w_range: tuple[int, int]) -> list[dict]:
        lo, hi = w_range
        return [
            it for it in items
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
        if not result.slots[slot]:
            result.gaps.append(
                f"No {slot} in your wardrobe fits {occasion} wear at {temp_c:.0f}°C "
                f"(need warmth {w_lo}-{w_hi}, formality {f_lo}-{f_hi}). "
                f"Add one, or relax your filters."
            )

    # Optional slots: outerwear only when cold, accessories when any exist.
    if temp_c < OUTERWEAR_MAX_TEMP_C:
        fill("outerwear", CAP_OPTIONAL, relax_until_found=True)
    accessory_pool = filter_slot("accessory", (w_lo, w_hi)) or filter_slot(
        "accessory", (1, 5)
    )
    if accessory_pool:
        result.slots["accessory"] = sorted(accessory_pool, key=lambda it: it["id"])
        if len(result.slots["accessory"]) > CAP_OPTIONAL:
            result.slots["accessory"] = rng.sample(result.slots["accessory"], CAP_OPTIONAL)

    return result
