"""RecommendationService: orchestrates weather -> candidates -> stylist -> response.

Single entry point for a recommendation. Never raises for "soft" problems
(weather unavailable, model down, invalid model answers) — it degrades:
weather falls back to a mild-day assumption, the stylist falls back to a
deterministic pick, and gaps are reported to the UI.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .. import repo
from ..config import AppConfig
from ..llm.provider import OllamaProvider
from ..models import OutfitItem, RecommendResponse, Weather
from . import stylist
from .candidates import select
from .weather import WeatherService, WeatherUnavailable

# Assumed temperature when weather is unavailable and not overridden.
MILD_TEMP_C = 15.0


class RecommendationService:
    def __init__(self):
        self._providers: dict[str, OllamaProvider] = {}

    def _provider(self, ollama_url: str) -> OllamaProvider:
        if ollama_url not in self._providers:
            self._providers[ollama_url] = OllamaProvider(ollama_url)
        return self._providers[ollama_url]

    def recommend(
        self,
        *,
        conn: sqlite3.Connection,
        config: AppConfig,
        city: str,
        model: str,
        ollama_url: str,
        weather_service: WeatherService,
        mood: str,
        occasion: str,
        weather_override_c: float | None = None,
    ) -> RecommendResponse:
        # 1. Weather: explicit override > live fetch > mild-day assumption.
        gaps: list[str] = []
        if weather_override_c is not None:
            weather = Weather(
                city=city,
                temperature_c=weather_override_c,
                apparent_temperature_c=weather_override_c,
                precipitation_mm=0.0,
                wind_speed_kmh=0.0,
                weather_code=0,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            gaps.append("Weather manually overridden.")
        else:
            try:
                weather = weather_service.current(city)
            except WeatherUnavailable:
                weather = Weather(
                    city=city,
                    temperature_c=MILD_TEMP_C,
                    apparent_temperature_c=MILD_TEMP_C,
                    precipitation_mm=0.0,
                    wind_speed_kmh=0.0,
                    weather_code=0,
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                gaps.append(
                    f"Live weather unavailable; assumed a mild {MILD_TEMP_C:.0f}°C. "
                    "You can set the temperature manually."
                )
        temp_c = weather.temperature_c

        # 2. Deterministic candidate selection over the whole wardrobe.
        items = [dict(row) for row in repo.items.list_all(conn)]
        rng_seed = int(datetime.now().strftime("%Y%m%d"))  # stable within a day
        candidates = select(items, temp_c=temp_c, occasion=occasion, rng_seed=rng_seed)
        gaps.extend(candidates.gaps)

        if not candidates.has_required:
            return RecommendResponse(
                title="No complete outfit possible",
                outfit=[],
                rationale=(
                    "Your wardrobe can't cover today's conditions: " + " ".join(gaps)
                ),
                source="fallback",
                gaps=gaps,
                weather=weather,
            )

        # 3. LLM stylist, with deterministic fallback.
        try:
            choice = stylist.choose(
                provider=self._provider(ollama_url),
                model=model,
                candidates=candidates,
                mood=mood,
                occasion=occasion,
            )
        except stylist.StylistError:
            choice = stylist.fallback_choice(candidates)
            gaps.append("Stylist model unavailable or returned an unusable answer; "
                        "showing a safe deterministic pick.")

        # 4. Assemble the outfit in display order.
        slot_order = ["top", "bottom", "outerwear", "shoes"]
        wanted_ids = list(choice.slot_picks.values()) + choice.accessory_ids
        by_id = {row["id"]: dict(row) for row in repo.items.get_many(conn, wanted_ids)}
        outfit: list[OutfitItem] = []
        for slot in slot_order:
            item_id = choice.slot_picks.get(slot)
            if item_id is not None and item_id in by_id:
                outfit.append(OutfitItem(slot=slot, item=by_id[item_id]))
        for acc_id in choice.accessory_ids:
            if acc_id in by_id:
                outfit.append(OutfitItem(slot="accessory", item=by_id[acc_id]))

        # 5. Log to history for future feedback features.
        repo.history.add(
            conn,
            mood=mood,
            occasion=occasion,
            weather=weather.model_dump(),
            item_ids=[oi.item.id for oi in outfit],
            rationale=choice.rationale,
            source=choice.source,
        )

        return RecommendResponse(
            title=choice.title,
            outfit=outfit,
            rationale=choice.rationale,
            source=choice.source,
            gaps=gaps,
            weather=weather,
        )
