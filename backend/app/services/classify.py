"""ClassifyService: photo -> draft wardrobe items via a vision LLM.

The model sees one clothing photo — which may hold SEVERAL items (a
flat-lay, a shelf, an outfit laid out) — and drafts the fields it can
judge from appearance (name, detailed category, color, style tags) plus
best-guess warmth and formality scores for EVERY distinct wearable item.
The results are DRAFTS for the user to review in the item form — not
auto-saved — since misjudged warmth/formality would silently degrade
every future recommendation.

The broad `type` (recommendation slot) is derived server-side from the
validated category, never trusted from the model alone; an invalid or
mismatched type/category pair is rejected.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..categories import CATEGORY_SLOT, categories_for_prompt
from ..llm.provider import LlmProvider, extract_json_multi, image_message

SYSTEM_PROMPT = """You analyze a photo of one OR several clothing items from \
a personal wardrobe (e.g. a flat-lay, a shelf, an outfit laid out) and \
describe EVERY distinct wearable item as structured data. Judge colors \
precisely (e.g. "charcoal grey", not "grey"). Warmth is 1 (very light, e.g. \
a summer tee) to 5 (heavy winter item, e.g. a thick wool coat). Formality \
is 1 (gym wear) to 5 (black tie). Style tags are 2-3 short descriptive \
words per item. Respond with JSON only."""

USER_PROMPT = """Describe the clothing items in this photo. Respond with \
exactly this JSON shape — a top-level ARRAY of objects:
[
  {{
    "name": "short, natural name like 'Navy linen shirt'",
    "category": "the item's detailed category, one of the categories below",
    "color": "main color",
    "warmth": 1-5,
    "formality": 1-5,
    "style_tags": "comma-separated tags"
  }}
]

Supported categories (pick the closest match; the broad type is derived from it):
{categories}

Rules: find EVERY distinct wearable item. Ignore non-wearables (hangers, \
furniture, packaging, background). A photo with one item must return a \
one-element array. Do not invent items that aren't visible. At most 8 items. \
Each item's "category" must be exactly one of the listed categories."""


class ClassificationError(Exception):
    """Vision model failed twice or Ollama unreachable."""


@dataclass
class DraftItem:
    name: str
    category: str
    type: str  # broad slot, derived from the category
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

    category = raw.get("category")
    if category not in CATEGORY_SLOT:
        raise ValueError(
            f"'category' must be one of the supported categories, got {category!r}"
        )
    slot = CATEGORY_SLOT[category]

    # A type claim is optional; when present it must agree with the
    # category's slot — a mismatched pair is rejected, never saved.
    type_ = raw.get("type")
    if type_ is None:
        type_ = slot
    elif type_ != slot:
        raise ValueError(
            f"category {category!r} belongs to type {slot!r}, not {type_!r}"
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
        category=category,
        type=type_,
        color=(color or "").strip() or None,
        warmth=score("warmth"),
        formality=score("formality"),
        style_tags=(tags or "").strip() or None,
    )


MAX_ITEMS = 8


class _NoValidItems(ValueError):
    """The reply parsed but yielded no wearable items (empty array or
    every element failed validation). Maps to a distinct ClassificationError
    message so clients can tell 'nothing detected' from 'reply garbage'."""


def classify_multi(
    provider: LlmProvider,
    model: str,
    image_b64: str,
) -> list[DraftItem]:
    """Ask the vision model for EVERY item in the photo; validate each.

    Elements that fail _validate are dropped rather than failing the
    whole batch. If parsing/validation yields zero items, that counts as
    an invalid reply: one retry with the error appended. Raises
    ClassificationError after two zero-item (or unreachable) attempts.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        image_message(
            USER_PROMPT.format(categories=categories_for_prompt()), image_b64
        ),
    ]

    last_error: ValueError | None = None
    reply: str | None = None
    for _attempt in range(2):
        try:
            # Vision classification is a judgment, not creative writing:
            # low temperature keeps repeated uploads of one item consistent.
            reply = provider.complete(messages, model, temperature=0.2)
            drafts: list[DraftItem] = []
            errors: list[str] = []
            for element in extract_json_multi(reply):
                try:
                    drafts.append(_validate(element))
                except ValueError as exc:
                    # One bad element must not sink its valid neighbours.
                    errors.append(str(exc))
            if not drafts:
                if errors:
                    raise _NoValidItems(
                        f"reply contained no valid items "
                        f"({len(errors)} bad): " + "; ".join(errors[:3])
                    )
                raise _NoValidItems("reply contained no items")
            return drafts[:MAX_ITEMS]
        except (ValueError, KeyError) as exc:
            last_error = exc if isinstance(exc, ValueError) else ValueError(str(exc))
            messages = messages + [
                {"role": "assistant", "content": reply if reply is not None else ""},
                {"role": "user", "content": (
                    f"Your reply was invalid: {last_error}. "
                    "Answer again with the exact JSON shape."
                )},
            ]
        except Exception as exc:  # network/model down
            raise ClassificationError(f"model call failed: {exc}") from exc

    if isinstance(last_error, _NoValidItems):
        raise ClassificationError("model found no wearable items") from last_error
    raise ClassificationError(f"model failed twice: {last_error}")
