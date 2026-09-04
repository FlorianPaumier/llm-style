"""ClassifyService: photo -> draft wardrobe item via a vision LLM.

The model sees one clothing photo and drafts the fields it can judge
from appearance (name, type, color, style tags) plus best-guess warmth
and formality scores. The result is a DRAFT for the user to review in
the item form — not auto-saved — since misjudged warmth/formality would
silently degrade every future recommendation.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..llm.provider import LlmProvider, extract_json, image_message

SYSTEM_PROMPT = """You analyze a photo of one clothing item from a personal \
wardrobe and describe it as structured data. Judge color precisely (e.g. \
"charcoal grey", not "grey"). Warmth is 1 (very light, e.g. a summer tee) to \
5 (heavy winter item, e.g. a thick wool coat). Formality is 1 (gym wear) to \
5 (black tie). Style tags are 2-3 short descriptive words. Respond with JSON only."""

USER_PROMPT = """Describe this clothing item. Respond with exactly this JSON shape:
{{
  "name": "short, natural name like 'Navy linen shirt'",
  "type": "top" | "bottom" | "shoes" | "outerwear" | "accessory",
  "color": "main color",
  "warmth": 1-5,
  "formality": 1-5,
  "style_tags": "comma-separated tags"
}}

Rules: the photo shows exactly one item; classify that item. If part of a \
second garment is visible, ignore it."""


class ClassificationError(Exception):
    """Vision model failed twice or Ollama unreachable."""


@dataclass
class DraftItem:
    name: str
    type: str
    color: str | None
    warmth: int
    formality: int
    style_tags: str | None


VALID_TYPES = {"top", "bottom", "shoes", "outerwear", "accessory"}


def _validate(raw: dict) -> DraftItem:
    """Raise ValueError with a fix-it message if the draft is unusable."""
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' must be a non-empty string")

    type_ = raw.get("type")
    if type_ not in VALID_TYPES:
        raise ValueError(
            f"'type' must be one of {sorted(VALID_TYPES)}, got {type_!r}"
        )

    color = raw.get("color")
    if color is not None and not isinstance(color, str):
        raise ValueError("'color' must be a string or null")

    def score(field: str) -> int:
        val = raw.get(field)
        if not isinstance(val, (int, float)) or isinstance(val, bool) \
                or not 1 <= int(val) <= 5:
            raise ValueError(f"'{field}' must be a number between 1 and 5")
        return int(val)

    tags = raw.get("style_tags")
    if tags is not None and not isinstance(tags, str):
        raise ValueError("'style_tags' must be a string or null")

    return DraftItem(
        name=name.strip(),
        type=type_,
        color=(color or "").strip() or None,
        warmth=score("warmth"),
        formality=score("formality"),
        style_tags=(tags or "").strip() or None,
    )


def classify(
    provider: LlmProvider,
    model: str,
    image_b64: str,
) -> DraftItem:
    """Ask the vision model; validate; one retry with the error appended."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        image_message(USER_PROMPT, image_b64),
    ]

    last_error: ValueError | None = None
    for attempt in range(2):
        try:
            # Vision classification is a judgment, not creative writing:
            # low temperature keeps repeated uploads of one item consistent.
            reply = provider.complete(messages, model, temperature=0.2)
            return _validate(extract_json(reply))
        except (ValueError, KeyError) as exc:
            last_error = exc if isinstance(exc, ValueError) else ValueError(str(exc))
            messages = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": (
                    f"Your reply was invalid: {last_error}. "
                    "Answer again with the exact JSON shape."
                )},
            ]
        except Exception as exc:  # network/model down
            raise ClassificationError(f"model call failed: {exc}") from exc

    raise ClassificationError(f"model failed twice: {last_error}")
