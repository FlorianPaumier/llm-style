"""QuickAddService: photo -> saved wardrobe items in one call.

The normal flow is photo -> /api/classify (draft) -> review in the form ->
POST /api/items (save). Quick add skips the form: the vision model's drafts
become items as-is. This is explicitly "trust the draft" — misjudged
warmth/formality go straight into the wardrobe — the price of not opening
the form. A photo may contain several garments (flat-lay); every detected
item is saved, each claiming its own copy of the photo bytes. Callers get
ClassificationError/ValueError back and map them to 503s; nothing here
touches HTTP.
"""
from __future__ import annotations

import base64
import sqlite3

from .. import repo
from ..config import AppConfig
from ..models import Item, ItemIn, QuickAddResponse
from . import classify, images


def quick_add(
    conn: sqlite3.Connection,
    *,
    photo_bytes: bytes,
    ext: str,
    persona_id: int | None,
    provider_factory,
    config: AppConfig,
) -> QuickAddResponse:
    """One photo -> every detected item saved, draft fields verbatim.

    provider_factory(ollama_url) returns the LLM provider to use (the
    recommender's provider_for seam — tests swap it for fakes).
    Raises classify.ClassificationError (model/network failed) or
    ValueError (no usable draft) for the caller to map.
    """
    settings = repo.settings.get(conn)
    ollama_url = settings["ollama_url"] or config.default_ollama_url
    vision_model = settings["vision_model"] or config.default_vision_model

    drafts = classify.classify_multi(
        provider_factory(ollama_url),
        vision_model,
        base64.b64encode(photo_bytes).decode("ascii"),
    )

    # Everything that can fail runs before any photo touches disk, so a
    # rejected draft never orphans a file for the startup sweep to find.
    # A draft that fails ItemIn validation (e.g. a too-long name) is
    # dropped rather than failing the whole batch — but an empty batch
    # is an unusable result and surfaces as ValueError.
    payloads: list[ItemIn] = []
    for draft in drafts:
        try:
            payloads.append(
                ItemIn(
                    name=draft.name,
                    category=draft.category,
                    type=draft.type,
                    color=draft.color,
                    warmth=draft.warmth,
                    formality=draft.formality,
                    style_tags=draft.style_tags,
                )
            )
        except Exception:
            continue  # skip this draft, keep the rest of the photo
    if not payloads:
        raise ValueError("no valid items in draft")

    persona = (
        repo.personas.get(conn, persona_id)
        if persona_id
        else repo.personas.first(conn)
    )

    items: list[Item] = []
    for payload in payloads:
        # One draft photo per item so each can be claimed (and later
        # replaced/deleted) independently.
        token = images.save_draft_image(photo_bytes, ext)
        row = repo.items.create(conn, payload, persona_id=persona["id"])
        final = images.claim_image(token, row["id"])
        if final:
            repo.items.update_image_path(conn, row["id"], final)
            row = repo.items.get(conn, row["id"])
        items.append(repo.items.to_item(row))
    return QuickAddResponse(items=items)
