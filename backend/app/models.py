"""Pydantic schemas for API requests and responses."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .categories import CATEGORY_SLOT

ItemType = Literal["top", "bottom", "shoes", "outerwear", "accessory"]
Occasion = Literal["gym", "casual", "work", "smart", "formal"]
Slot = Literal["top", "bottom", "shoes", "outerwear", "accessory"]
Gender = Literal["male", "female", "unspecified"]
ItemSortKey = Literal["name", "type", "category", "color", "warmth", "formality", "style_tags"]

# Photos are addressed by opaque server-issued tokens (draft-<hex>.<ext>,
# returned by /api/classify), never by filesystem paths.
PHOTO_TOKEN_RE = re.compile(r"^draft-[0-9a-f]{12}\.(?:jpg|jpeg|png|webp)$")


def _check_photo_token(value: str | None) -> str | None:
    if value is not None and not PHOTO_TOKEN_RE.match(value):
        raise ValueError("photo_token must be a token issued by /api/classify")
    return value


class Persona(BaseModel):
    id: int
    name: str
    description: str | None = None
    gender: Gender  # always concrete in responses (unspecified by default)


class PersonaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    # Free-text preferences the stylist LLM should respect (e.g. "no hats").
    # POST: optional. PUT: absent keeps, null/"" clears, text replaces.
    description: str | None = Field(default=None, max_length=500)
    # POST: optional (null/absent = unspecified); steers the stylist's
    # phrasing and silhouette judgment, never the candidate selection.
    gender: Gender | None = None


class PersonaUpdate(BaseModel):
    """PUT /api/personas/{id} payload — merge semantics like /api/settings:
    a key absent from the payload keeps its current value; a key sent
    (including null/"" for description) sets it. A null gender resets to
    unspecified."""
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=500)
    gender: Gender | None = None


class ItemFields(BaseModel):
    """The wardrobe-item fields a client may set.

    `category` is the detailed classification and the primary field: the
    server derives the broad `type` (recommendation slot) from it. A
    client may also claim `type` explicitly, but a type/category pair
    that disagree is rejected — never silently saved.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    category: str = Field(description="detailed garment category")
    type: ItemType | None = None  # optional claim; derived/validated below
    color: str | None = Field(default=None, max_length=50)
    warmth: int = Field(ge=1, le=5)
    formality: int = Field(ge=1, le=5)
    style_tags: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        if v not in CATEGORY_SLOT:
            raise ValueError(
                f"'category' must be one of the supported categories, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _derive_type(self):
        slot = CATEGORY_SLOT[self.category]
        if self.type is None:
            self.type = slot
        elif self.type != slot:
            raise ValueError(
                f"category {self.category!r} belongs to type {slot!r}, not {self.type!r}"
            )
        return self


class ItemIn(ItemFields):
    """Create payload. photo_token optionally attaches a classified photo;
    persona_id optionally targets another wardrobe (default: first persona)."""

    photo_token: str | None = None
    persona_id: int | None = Field(default=None, ge=1)

    @field_validator("photo_token")
    @classmethod
    def _validate_token(cls, v):
        return _check_photo_token(v)


class ItemUpdate(ItemFields):
    """Update payload (full field replacement). Photos are managed through
    the /api/items/{id}/photo endpoints so an edit can never destroy one.
    persona_id moves the item to another wardrobe when sent."""

    persona_id: int | None = Field(default=None, ge=1)


class Item(ItemFields):
    """A wardrobe item as returned by the API. No filesystem paths leak.
    The broad `type` is always present (derived server-side) so existing
    clients and recommendation history stay compatible."""
    id: int
    type: ItemType  # always concrete in responses
    times_worn: int
    persona_id: int
    has_photo: bool
    photo_url: str | None = None


class ItemListResponse(BaseModel):
    items: list[Item]
    total: int
    page: int
    page_size: int
    pages: int


class PhotoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_token: str

    @field_validator("photo_token")
    @classmethod
    def _validate_token(cls, v):
        return _check_photo_token(v)


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    ollama_url: str | None = Field(default=None, max_length=300)
    vision_model: str | None = Field(default=None, max_length=100)


class Settings(BaseModel):
    city: str
    model: str
    ollama_url: str
    vision_model: str


class DraftItemResponse(BaseModel):
    """Vision-model draft of a wardrobe item, for user review in the form.
    The category is the primary field; `type` is the slot derived from it."""
    name: str
    category: str
    type: ItemType
    color: str | None
    warmth: int
    formality: int
    style_tags: str | None
    photo_token: str


class Weather(BaseModel):
    city: str
    temperature_c: float
    apparent_temperature_c: float
    precipitation_mm: float
    wind_speed_kmh: float
    weather_code: int
    fetched_at: str


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mood: str = Field(min_length=1, max_length=500)
    occasion: Occasion = "casual"
    # What the person will actually be doing ("Christmas dinner", "zoo
    # day", "wedding") — steers the stylist and guarantees a warm-layer
    # option in the candidate pool.
    activity: str | None = Field(default=None, max_length=200)
    weather_override_c: float | None = Field(default=None, ge=-60, le=60)
    # Who is getting dressed. None/empty = first persona (backward
    # compatible). Multiple personas => coordinated outfits, one each.
    persona_ids: list[int] | None = Field(default=None)
    # How many outfit options per persona (1-5). Each option differs from
    # the ones before it (variety rules + fallback rotation).
    count: int = Field(default=1, ge=1, le=5)


class OutfitItem(BaseModel):
    slot: Slot
    item: Item


class PersonaOutfit(BaseModel):
    """One person's outfit within a (possibly paired) recommendation."""
    persona_id: int
    persona_name: str
    title: str
    outfit: list[OutfitItem]
    rationale: str
    source: Literal["llm", "fallback"]
    gaps: list[str] = []
    history_id: int | None = None
    # 1-based position among this persona's options in the same request
    # (always 1 unless RecommendRequest.count > 1).
    option: int = 1


class RecommendResponse(BaseModel):
    # Top-level fields mirror the first selected persona so existing
    # clients keep working; `outfits` carries one entry per persona.
    title: str
    outfit: list[OutfitItem]
    rationale: str
    source: Literal["llm", "fallback"]
    gaps: list[str] = []
    weather: Weather | None = None
    history_id: int | None = None
    outfits: list[PersonaOutfit] = []


class OutfitHistoryEntry(BaseModel):
    id: int
    created_at: str
    mood: str
    occasion: str
    weather: Weather | None = None
    items: list[Item] = []
    rationale: str | None = None
    source: str | None = None
    worn_at: str | None = None
    persona_id: int | None = None


class MarkWornResponse(BaseModel):
    history_id: int
    already_worn: bool
    item_ids: list[int] = []


class JobCreated(BaseModel):
    job_id: str
    status_url: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    result: RecommendResponse | DraftItemResponse | list[BulkClassifyResultItem] | None = None
    error: str | None = None
    # Bulk jobs report live progress while queued/running; other jobs
    # simply omit it (serialized as null) — existing clients ignore it.
    progress: dict | None = None


class BulkClassifyResultItem(BaseModel):
    """One photo's outcome in a bulk classify job.

    ok=True rows carry the usual DraftItemResponse fields (the photo is
    already saved as a draft, ready to be claimed on item save);
    ok=False rows carry the reason that single photo failed.
    """
    ok: bool
    filename: str
    draft: DraftItemResponse | None = None
    error: str | None = None


class ClassifyResponse(BaseModel):
    """One photo's classification: one entry per detected item, each with
    its own photo token (the photo is saved once per draft)."""
    items: list[DraftItemResponse]


class QuickAddResponse(BaseModel):
    """One quick-add photo's saved items: one per detected garment."""
    items: list[Item]


class AppDownload(BaseModel):
    primary_url: str
    lan_urls: list[str] = []
    qr_svg_url: str | None = None
    manifest_url: str = "/manifest.webmanifest"
    install_hint: str
