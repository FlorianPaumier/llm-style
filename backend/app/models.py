"""Pydantic schemas for API requests and responses."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemType = Literal["top", "bottom", "shoes", "outerwear", "accessory"]
Occasion = Literal["gym", "casual", "work", "smart", "formal"]


class ItemIn(BaseModel):
    """Payload for creating an item."""
    name: str = Field(min_length=1, max_length=100)
    type: ItemType
    color: str | None = Field(default=None, max_length=50)
    warmth: int = Field(ge=1, le=5)
    formality: int = Field(ge=1, le=5)
    style_tags: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    image_path: str | None = Field(default=None, max_length=300)


class Item(ItemIn):
    """A wardrobe item as stored and returned by the API."""
    id: int
    times_worn: int

    model_config = ConfigDict(from_attributes=True)


class SettingsIn(BaseModel):
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
    """Vision-model draft of a wardrobe item, for user review in the form."""
    name: str
    type: ItemType
    color: str | None
    warmth: int
    formality: int
    style_tags: str | None
    image_path: str | None = None


class Weather(BaseModel):
    city: str
    temperature_c: float
    apparent_temperature_c: float
    precipitation_mm: float
    wind_speed_kmh: float
    weather_code: int
    fetched_at: str


class RecommendRequest(BaseModel):
    mood: str = Field(min_length=1, max_length=500)
    occasion: Occasion = "casual"
    weather_override_c: float | None = Field(default=None, ge=-60, le=60)


class OutfitItem(BaseModel):
    slot: str
    item: Item


class RecommendResponse(BaseModel):
    title: str
    outfit: list[OutfitItem]
    rationale: str
    source: Literal["llm", "fallback"]
    gaps: list[str] = []
    weather: Weather | None = None
