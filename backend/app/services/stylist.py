"""LlmStylist: the LLM half of the engine.

Builds a compact prompt from the candidate set, asks the model to pick
one outfit per slot and explain why it matches the mood, validates the
IDs strictly against the role constraints, retries once on a bad answer,
and falls back to a deterministic pick if the model still fails.

Role constraints (shared with the deterministic fallback):
- exactly one primary upper (or a one-piece, which replaces upper+lower);
- a layer (cardigan) may be added OVER the primary upper — never instead
  of it, and never two primary uppers (vest + blouse is out);
- exactly one primary lower, plus optionally an underlayer (tights/
  leggings) when the outfit is skirt/dress/shorts based;
- exactly one footwear item; outerwear and accessories stay optional and
  weather-aware.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..categories import (
    UNDERLAYER_HOST_CATEGORIES,
    ROLE_LAYER_UPPER,
    ROLE_LOWER_UNDERLAYER,
    ROLE_ONE_PIECE,
    ROLE_PRIMARY_LOWER,
    ROLE_PRIMARY_UPPER,
    item_category,
)
from ..llm.provider import LlmProvider, extract_json
from ..models import Weather
from .candidates import CandidateSet, FORMALITY_TARGET, warmth_band

SYSTEM_PROMPT = """You are an exacting personal stylist choosing one complete, \
wearable outfit from a small candidate list drawn from the user's real wardrobe. \
Every item ID you pick must come from the list for that slot. Do not suggest a \
partial look, alternatives, or items the person does not own. First make the \
outfit complete and practical for the weather and activity; then make its \
colours, proportions, textures, and formality feel intentionally coordinated \
with the user's mood. Keep the rationale warm, short (2-3 sentences) and \
specific about those choices. Respond with JSON only, no prose outside it."""

USER_PROMPT = """Today's context:
- Weather: {weather_summary}
- Occasion: {occasion}
- User's mood: "{mood}"
{activity_notes}{persona_notes}{coordination}{recent}- Candidate items from the wardrobe \
(id | category | name | color | style tags | warmth 1-5 | formality 1-5), \
grouped by broad slot:
{candidates}

Pick one outfit. Respond with exactly this JSON shape:
{{
  "title": "short outfit name",
  "item_ids": {{
    "top": <id>,
    "layer": <id or null>,
    "bottom": <id or null>,
    "underlayer": <id or null>,
    "shoes": <id>,
    "outerwear": <id or null>,
    "accessories": [<ids>, ...]
  }},
  "rationale": "why this outfit matches the mood, weather and occasion"
}}

Quality bar: return one finished look someone can put on immediately, not a \
collection of individually suitable pieces. Before answering, check that the \
base outfit is complete, its colours and formality work together, and it is \
practical for the stated weather, occasion, activity, and personal notes. A \
normal outfit needs a top + bottom + shoes; a one-piece outfit needs the \
one-piece + shoes. Add outerwear when cold, wet, or windy weather makes it \
needed and a suitable candidate is available. Accessories only earn a place \
when they improve the finished look or weather protection.

Rules: "top" must be a primary top (t-shirt, shirt, blouse, polo, tank top, \
vest, sweater, hoodie or sweatshirt) or a one-piece (dress, jumpsuit, \
romper) — a cardigan is a layer, never the top. "layer" (optional) is one \
cardigan worn over the top. "bottom" is required unless "top" is a \
one-piece, which replaces both top and bottom (then "bottom" must be null). \
"underlayer" (optional) is tights or leggings, allowed only with a skirt, \
dress or shorts outfit — it never replaces "bottom", and tights under \
trousers or jeans are wrong. "shoes" is required and must be an ID from the \
shoes list. "outerwear" and "accessories" are optional; use null / [] if \
none fit. Choose at most 2 accessories. Use your judgment on accessories: \
skip them when they don't suit the weather, the occasion, or the person's \
notes — an outfit works without them. {variety_rule}"""

COORDINATION_RULES = """- Others in the group are already wearing: {summaries}
  Complement them — coordinate colors and overall dressiness so the group
  looks together, without copying the same statement pieces.
"""

PERSONA_NOTES = """- Notes about this person: {description} — respect these \
preferences (e.g. avoid types they say don't suit them).
"""

GENDER_NOTES = """- This person is {phrase} — factor that into the fits, \
cuts and silhouettes you suggest for them.
"""

ACTIVITY_NOTES = """- What they'll be doing: "{activity}" — dress for the \
activity itself: a wedding or a company Christmas dinner wants dressy, \
put-together pieces; a zoo day or a walk wants comfortable casuals. For \
dinners, celebrations and evening events, include the warm layer over the \
top, and add a coat from the outerwear list when the weather calls for one.
"""

RECENT_OUTFITS = """- Already suggested recently (do not repeat): {recent_outfits}
  When the wardrobe allows, vary your picks from these — reusing a piece
  is fine, but not the same combination. Aim for the best varied mix that
  still matches the mood, weather and occasion.
"""

VARIETY_RULE = """This is not the first option for today: vary your picks \
from the recently suggested ones — reuse a piece if you must, but never \
the same combination, and make it a genuinely different take on the mood."""

NO_RECENT_OUTFITS_RULE = """Aim for the best mix of pieces that expresses \
the mood — not just the safest pick."""

FALLBACK_RATIONALE = (
    "Quick pick matched to today's weather and occasion — the stylist model "
    "was unavailable, so here's a safe combination instead."
)


@dataclass
class StylistChoice:
    title: str
    slot_picks: dict[str, int]           # top/layer/bottom/underlayer/shoes/outerwear -> item id
    accessory_ids: list[int]
    rationale: str
    source: str                          # "llm" | "fallback"


class StylistError(Exception):
    """Model failed twice; caller should use the deterministic fallback."""


def _weather_summary(candidates: CandidateSet, weather: Weather | None) -> str:
    if weather is None:
        return f"{candidates.temp_c:.0f}°C"
    parts = [f"{weather.temperature_c:.0f}°C"]
    if abs(weather.apparent_temperature_c - weather.temperature_c) >= 2:
        parts[0] += f" (feels like {weather.apparent_temperature_c:.0f}°C)"
    if weather.precipitation_mm > 0.5:
        parts.append("rain expected")
    if weather.wind_speed_kmh >= 25:
        parts.append(f"wind {weather.wind_speed_kmh:.0f} km/h")
    return ", ".join(parts)


def build_prompt(
    candidates: CandidateSet,
    mood: str,
    occasion: str,
    weather: Weather | None = None,
    context_outfits: list[str] | None = None,
    persona_description: str | None = None,
    recent_outfits: list[str] | None = None,
    persona_gender: str | None = None,
    activity: str | None = None,
) -> str:
    """Build the stylist prompt. context_outfits are one-line summaries of
    outfits already chosen for others in the group (pair coordination).
    persona_description is free-text preferences the person has stated
    (e.g. "no hats"); the stylist must respect them. recent_outfits are
    one-line summaries of outfits suggested to this person recently
    (history + earlier options in the same request): the stylist must
    vary from them when the wardrobe allows. persona_gender ("male" /
    "female" / unspecified) informs phrasing and silhouette judgment —
    it never changes which items are candidates. activity is what the
    person will actually be doing ("Christmas dinner", "zoo day"); the
    stylist dresses for it and includes a warm layer for events."""
    lines = []
    for slot, items in candidates.slots.items():
        for it in items:
            lines.append(
                f"- {slot} | id {it['id']} | {it['category']} | {it['name']}"
                f" | color: {it['color'] or 'n/a'}"
                f" | tags: {it['style_tags'] or 'n/a'}"
                f" | warmth {it['warmth']} | formality {it['formality']}"
            )
    candidates_text = "\n".join(lines) or "(no candidates)"
    if context_outfits:
        coordination = COORDINATION_RULES.format(
            summaries="; ".join(context_outfits)
        )
    else:
        coordination = ""
    if persona_description and persona_description.strip():
        persona_notes = PERSONA_NOTES.format(description=persona_description.strip())
    else:
        persona_notes = ""
    if persona_gender == "male":
        persona_notes += GENDER_NOTES.format(phrase="a man")
    elif persona_gender == "female":
        persona_notes += GENDER_NOTES.format(phrase="a woman")
    if activity and activity.strip():
        activity_notes = ACTIVITY_NOTES.format(activity=activity.strip())
    else:
        activity_notes = ""
    recent = recent_outfits or []
    if recent:
        recent_section = RECENT_OUTFITS.format(recent_outfits="; ".join(recent))
        variety_rule = VARIETY_RULE
    else:
        recent_section = ""
        variety_rule = NO_RECENT_OUTFITS_RULE
    return USER_PROMPT.format(
        weather_summary=_weather_summary(candidates, weather),
        occasion=occasion,
        mood=mood,
        activity_notes=activity_notes,
        persona_notes=persona_notes,
        coordination=coordination,
        recent=recent_section,
        candidates=candidates_text,
        variety_rule=variety_rule,
    )


def _role_ids(candidates: CandidateSet, slot: str, role: str) -> set[int]:
    return {
        it["id"] for it in candidates.slots.get(slot, []) if it.get("role") == role
    }


def _all_ids(candidates: CandidateSet, slot: str) -> set[int]:
    return {it["id"] for it in candidates.slots.get(slot, [])}


def _id_role(candidates: CandidateSet, slot: str, item_id: int) -> str | None:
    for it in candidates.slots.get(slot, []):
        if it["id"] == item_id:
            return it.get("role")
    return None


def _validate(raw: dict, candidates: CandidateSet) -> dict:
    """Raise ValueError with a fix-it message if the answer is unusable."""
    item_ids = raw.get("item_ids")
    if not isinstance(item_ids, dict):
        raise ValueError("reply is missing the item_ids object")

    top = item_ids.get("top")
    if top is None:
        raise ValueError("required slot 'top' was left empty")
    if top not in _all_ids(candidates, "top"):
        raise ValueError(f"ID {top!r} is not a candidate for slot 'top'")
    top_role = _id_role(candidates, "top", top)
    if top_role == ROLE_LAYER_UPPER:
        raise ValueError(
            f"ID {top!r} is a layer (cardigan), not a top — put it in 'layer' "
            "and pick a primary top for 'top'"
        )
    if top_role != ROLE_PRIMARY_UPPER and top_role != ROLE_ONE_PIECE:
        raise ValueError(f"ID {top!r} cannot serve as the top")
    one_piece = top_role == ROLE_ONE_PIECE

    picks: dict[str, int] = {"top": top}

    layer = item_ids.get("layer")
    if layer is not None:
        if layer not in _role_ids(candidates, "top", ROLE_LAYER_UPPER):
            raise ValueError(
                f"ID {layer!r} is not a layer candidate — 'layer' takes a "
                "cardigan-style piece, and only one primary top is allowed"
            )
        if layer == top:
            raise ValueError(f"ID {layer!r} cannot be both 'top' and 'layer'")
        picks["layer"] = layer

    bottom = item_ids.get("bottom")
    if one_piece:
        if bottom is not None:
            raise ValueError(
                "a one-piece (dress/jumpsuit/romper) replaces both top and "
                "bottom — set 'bottom' to null"
            )
    else:
        if bottom is None:
            raise ValueError("required slot 'bottom' was left empty")
        if bottom not in _all_ids(candidates, "bottom"):
            raise ValueError(f"ID {bottom!r} is not a candidate for slot 'bottom'")
        if _id_role(candidates, "bottom", bottom) != ROLE_PRIMARY_LOWER:
            raise ValueError(
                f"ID {bottom!r} is an underlayer (tights/leggings) — it works "
                "under a skirt, dress or shorts but never replaces the bottom; "
                "use 'underlayer' for it"
            )
        picks["bottom"] = bottom

    underlayer = item_ids.get("underlayer")
    if underlayer is not None:
        if underlayer not in _role_ids(candidates, "bottom", ROLE_LOWER_UNDERLAYER):
            raise ValueError(
                f"ID {underlayer!r} is not an underlayer candidate — 'underlayer' "
                "takes tights or leggings only"
            )
        bottom_category = item_category(
            next(it for it in candidates.slots.get("bottom", []) if it["id"] == bottom)
        ) if bottom is not None else None
        host_ok = one_piece or (
            bottom_category in UNDERLAYER_HOST_CATEGORIES
        )
        if not host_ok:
            raise ValueError(
                f"ID {underlayer!r} (tights/leggings) pairs with a skirt, dress "
                "or shorts — not with this bottom"
            )
        picks["underlayer"] = underlayer

    shoes = item_ids.get("shoes")
    if shoes is None:
        raise ValueError("required slot 'shoes' was left empty")
    if shoes not in _all_ids(candidates, "shoes"):
        raise ValueError(f"ID {shoes!r} is not a candidate for slot 'shoes'")
    picks["shoes"] = shoes

    outerwear = item_ids.get("outerwear")
    if outerwear is not None:
        if outerwear not in _all_ids(candidates, "outerwear"):
            raise ValueError(f"ID {outerwear!r} is not a candidate for slot 'outerwear'")
        picks["outerwear"] = outerwear

    raw_accessories = item_ids.get("accessories") or []
    if not isinstance(raw_accessories, list):
        raise ValueError("'accessories' must be a list of IDs")
    accessories = []
    for aid in raw_accessories[:2]:
        if aid not in _all_ids(candidates, "accessory"):
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


def fallback_choice(candidates: CandidateSet, avoid: set[int] | None = None) -> StylistChoice:
    """Deterministic outfit enforcing the same role constraints as the
    validated LLM reply: one primary upper and one primary lower (or a
    one-piece when no primary upper exists), optionally a compatible
    layer and underlayer, never competing primary garments.

    Per slot, the candidate whose formality is closest to the occasion's
    target wins; ties break by lower id.

    avoid: item ids already suggested (recent history, earlier options in
    the same request). Candidates outside the avoid-set win; an avoided
    item is still picked when its slot offers no alternative — a small
    wardrobe must never dead-end on variety."""
    target = FORMALITY_TARGET[candidates.occasion]
    avoid = avoid or set()

    def pick(pool: list[dict]) -> dict | None:
        if not pool:
            return None
        fresh = [it for it in pool if it["id"] not in avoid]
        best_pool = fresh or pool
        return min(best_pool, key=lambda it: (abs(it["formality"] - target), it["id"]))

    picks: dict[str, int] = {}
    top = pick(candidates.primary_upper or candidates.one_piece)
    if top is not None:
        picks["top"] = top["id"]
    if top is not None and top.get("role") != ROLE_ONE_PIECE:
        bottom = pick(candidates.primary_lower)
        if bottom is not None:
            picks["bottom"] = bottom["id"]
    # Layer (cardigan) over the primary upper, and an underlayer under a
    # skirt/dress/shorts — the candidate pools are already weather-filtered,
    # so anything present here fits today's temperature.
    layer = pick(candidates.layer_upper)
    if layer is not None and top is not None and layer["id"] != top["id"]:
        picks["layer"] = layer["id"]
    bottom_category = _bottom_category(candidates, picks)
    underlayer_ok = (
        (top is not None and top.get("role") == ROLE_ONE_PIECE)
        or bottom_category in UNDERLAYER_HOST_CATEGORIES
    )
    underlayer = pick(candidates.lower_underlayer)
    if underlayer is not None and underlayer_ok:
        picks["underlayer"] = underlayer["id"]

    for slot in ("shoes", "outerwear"):
        best = pick(candidates.slots.get(slot) or [])
        if best is not None:
            picks[slot] = best["id"]
    accessories: list[int] = []
    # Weather-aware accessory pick (at most 1): only an accessory whose
    # warmth fits today's band, lowest id; none at all if the wardrobe's
    # accessories are all wrong for the temperature (no wool scarf in July).
    w_lo, w_hi = warmth_band(candidates.temp_c)
    in_band = [
        it for it in (candidates.slots.get("accessory") or [])
        if w_lo <= it["warmth"] <= w_hi
    ]
    best_accessory = pick(in_band)
    if best_accessory is not None:
        accessories = [best_accessory["id"]]
    return StylistChoice(
        title="Safe pick",
        slot_picks=picks,
        accessory_ids=accessories,
        rationale=FALLBACK_RATIONALE,
        source="fallback",
    )


def _bottom_category(candidates: CandidateSet, picks: dict[str, int]) -> str | None:
    """The picked primary lower's category, if any."""
    item_id = picks.get("bottom")
    if item_id is None:
        return None
    for it in candidates.slots.get("bottom", []):
        if it["id"] == item_id:
            return it.get("category")
    return None


def choose(
    provider: LlmProvider,
    model: str,
    candidates: CandidateSet,
    mood: str,
    occasion: str,
    weather: Weather | None = None,
    context_outfits: list[str] | None = None,
    persona_description: str | None = None,
    recent_outfits: list[str] | None = None,
    persona_gender: str | None = None,
    activity: str | None = None,
) -> StylistChoice:
    """Ask the model; validate; one retry with the error appended; then fallback.

    recent_outfits: one-line summaries of recently suggested outfits the
    stylist must vary from (see build_prompt). persona_gender steers
    phrasing/silhouettes in the prompt only. activity is what the person
    will be doing — the prompt dresses for it and asks for a warm layer
    at events; the candidate pool already guarantees the layer option."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(
            candidates, mood, occasion, weather, context_outfits,
            persona_description, recent_outfits, persona_gender, activity,
        )},
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
