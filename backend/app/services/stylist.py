"""LlmStylist: the LLM half of the engine.

Builds a compact prompt from the candidate set, asks the model to pick
one outfit per slot and explain why it matches the mood, validates the
IDs strictly, retries once on a bad answer, and falls back to a
deterministic pick if the model still fails.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..llm.provider import LlmProvider, extract_json
from .candidates import CandidateSet, FORMALITY_TARGET

SYSTEM_PROMPT = """You are a personal stylist choosing one outfit from a small \
candidate list drawn from the user's real wardrobe. Every item ID you pick must \
come from the list for that slot. Consider the user's mood above all: colors, \
textures and style should express it. Respect the weather and occasion. Keep \
the rationale warm, short (2-3 sentences) and specific about why this matches \
their mood. Respond with JSON only, no prose outside it."""

USER_PROMPT = """Today's context:
- Weather: {weather_summary}
- Occasion: {occasion}
- User's mood: "{mood}"

Candidate items from the wardrobe (id | type | color | style tags | warmth 1-5 | formality 1-5):
{candidates}

Pick one outfit. Respond with exactly this JSON shape:
{{
  "title": "short outfit name",
  "item_ids": {{
    "top": <id>,
    "bottom": <id>,
    "shoes": <id>,
    "outerwear": <id or null>,
    "accessories": [<ids>, ...]
  }},
  "rationale": "why this outfit matches the mood, weather and occasion"
}}

Rules: "top", "bottom" and "shoes" are required and must be IDs from those \
slots' lists. "outerwear" and "accessories" are optional; use null / [] if \
none fit. Choose at most 2 accessories."""

FALLBACK_RATIONALE = (
    "Quick pick matched to today's weather and occasion — the stylist model "
    "was unavailable, so here's a safe combination instead."
)


@dataclass
class StylistChoice:
    title: str
    slot_picks: dict[str, int]           # slot -> item id (top/bottom/shoes/outerwear)
    accessory_ids: list[int]
    rationale: str
    source: str                          # "llm" | "fallback"


class StylistError(Exception):
    """Model failed twice; caller should use the deterministic fallback."""


def build_prompt(candidates: CandidateSet, mood: str, occasion: str) -> str:
    lines = []
    for slot, items in candidates.slots.items():
        for it in items:
            lines.append(
                f"- {slot} | id {it['id']} | {it['name']} | color: {it['color'] or 'n/a'}"
                f" | tags: {it['style_tags'] or 'n/a'}"
                f" | warmth {it['warmth']} | formality {it['formality']}"
            )
    candidates_text = "\n".join(lines) or "(no candidates)"
    weather_summary = (
        f"{candidates.temp_c:.0f}°C, feels like a {candidates.occasion} day"
    )
    return USER_PROMPT.format(
        weather_summary=weather_summary,
        occasion=occasion,
        mood=mood,
        candidates=candidates_text,
    )


def _validate(raw: dict, candidates: CandidateSet) -> dict:
    """Raise ValueError with a fix-it message if the answer is unusable."""
    item_ids = raw.get("item_ids")
    if not isinstance(item_ids, dict):
        raise ValueError("reply is missing the item_ids object")

    valid = {slot: {it["id"] for it in items} for slot, items in candidates.slots.items()}
    picks: dict[str, int] = {}
    for slot in ("top", "bottom", "shoes"):
        picked = item_ids.get(slot)
        if picked is None:
            raise ValueError(f"required slot '{slot}' was left empty")
        if picked not in valid.get(slot, set()):
            raise ValueError(f"ID {picked!r} is not a candidate for slot '{slot}'")
        picks[slot] = picked

    outerwear = item_ids.get("outerwear")
    if outerwear is not None:
        if outerwear not in valid.get("outerwear", set()):
            raise ValueError(f"ID {outerwear!r} is not a candidate for slot 'outerwear'")
        picks["outerwear"] = outerwear

    raw_accessories = item_ids.get("accessories") or []
    if not isinstance(raw_accessories, list):
        raise ValueError("'accessories' must be a list of IDs")
    accessories = []
    for aid in raw_accessories[:2]:
        if aid not in valid.get("accessory", set()):
            raise ValueError(f"ID {aid!r} is not a candidate for slot 'accessory'")
        accessories.append(aid)

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("'title' must be a non-empty string")
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("'rationale' must be a non-empty string")

    return {
        "title": title.strip(),
        "picks": picks,
        "accessories": accessories,
        "rationale": rationale.strip(),
    }


def fallback_choice(candidates: CandidateSet) -> StylistChoice:
    """Deterministic outfit: per slot, the candidate whose formality is
    closest to the occasion's target; ties break by lower id."""
    target = FORMALITY_TARGET[candidates.occasion]
    picks: dict[str, int] = {}
    for slot in ("top", "bottom", "shoes", "outerwear"):
        pool = candidates.slots.get(slot) or []
        if not pool:
            continue
        best = min(pool, key=lambda it: (abs(it["formality"] - target), it["id"]))
        picks[slot] = best["id"]
    accessories = [
        it["id"] for it in (candidates.slots.get("accessory") or [])[:1]
    ]
    return StylistChoice(
        title="Safe pick",
        slot_picks=picks,
        accessory_ids=accessories,
        rationale=FALLBACK_RATIONALE,
        source="fallback",
    )


def choose(
    provider: LlmProvider,
    model: str,
    candidates: CandidateSet,
    mood: str,
    occasion: str,
) -> StylistChoice:
    """Ask the model; validate; one retry with the error appended; then fallback."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(candidates, mood, occasion)},
    ]
    if not candidates.has_required:
        # No complete outfit is possible; don't burn a model call.
        raise StylistError("required slots empty")

    last_error: ValueError | None = None
    for attempt in range(2):
        try:
            reply = provider.complete(messages, model)
            parsed = _validate(extract_json(reply), candidates)
            return StylistChoice(
                title=parsed["title"],
                slot_picks=parsed["picks"],
                accessory_ids=parsed["accessories"],
                rationale=parsed["rationale"],
                source="llm",
            )
        except (ValueError, KeyError) as exc:
            last_error = exc if isinstance(exc, ValueError) else ValueError(str(exc))
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": (
                    f"Your reply was invalid: {last_error}. "
                    "Answer again with the exact JSON shape, using only IDs from the lists."
                )},
            ]
        except Exception as exc:  # network/model down
            raise StylistError(f"model call failed: {exc}") from exc

    raise StylistError(f"model failed twice: {last_error}")
