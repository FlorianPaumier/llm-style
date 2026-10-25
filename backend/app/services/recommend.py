"""RecommendationService: orchestrates weather -> candidates -> stylist -> response.

Single entry point for a recommendation. Never raises for "soft" problems
(weather unavailable, model down, invalid model answers) — it degrades:
weather falls back to a mild-day assumption, the stylist falls back to a
deterministic pick, and gaps are reported to the UI.

Multi-persona: the pipeline runs once per selected persona with one shared
weather fetch. When several people are being dressed together, each stylist
call after the first is told what the others wear so it coordinates.

Variety: the candidate sample seed is random per request (re-asking the
same prompt re-samples the pool), and every stylist call is shown what was
suggested recently (history) and earlier in the same request (sibling
options), with a rule to vary. `count` asks for several outfit options per
persona; each option avoids the ones before it.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timezone

from .. import repo
from ..config import AppConfig
from ..llm.provider import OllamaProvider
from ..models import OutfitItem, PersonaOutfit, RecommendResponse, Weather
from . import stylist
from .candidates import select
from .weather import WeatherService, WeatherUnavailable

# Assumed temperature when weather is unavailable and not overridden.
MILD_TEMP_C = 15.0

# How many recent outfits per persona feed the "do not repeat" memory.
RECENT_MEMORY = 3


def _outfit_summary(conn: sqlite3.Connection, item_ids: list[int]) -> str:
    """One line describing a recently suggested outfit, for the prompt's
    'do not repeat' memory: 'navy tee, blue jeans, white sneakers'."""
    rows = repo.items.get_many(conn, item_ids)
    by_id = {row["id"]: row for row in rows}
    names = [by_id[i]["name"] for i in item_ids if i in by_id]
    return ", ".join(names[:5]) if names else "(empty outfit)"


class RecommendationService:
    def __init__(self):
        self._providers: dict[str, OllamaProvider] = {}

    def provider_for(self, ollama_url: str) -> OllamaProvider:
        """A cached provider per Ollama URL (shared client connections)."""
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
        activity: str | None = None,
        weather_override_c: float | None = None,
        persona_ids: list[int] | None = None,
        count: int = 1,
        rng_seed: int | None = None,
    ) -> RecommendResponse:
        # rng_seed injectable for deterministic tests; None = fresh random
        # per request so re-asking the same prompt varies the candidates.
        seed = rng_seed if rng_seed is not None else random.randrange(2**32)

        # 0. Resolve who is getting dressed; default = first persona.
        if persona_ids:
            resolved = [repo.personas.get(conn, pid) for pid in persona_ids]
            missing = [pid for pid, p in zip(persona_ids, resolved) if p is None]
            if missing:
                raise ValueError(f"Unknown persona id(s): {missing}")
            personas = [p for p in resolved if p is not None]
        else:
            personas = [repo.personas.first(conn)]

        # 1. Weather: explicit override > live fetch > mild-day assumption.
        # Fetched once, shared by every persona.
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

        # 2-3. Per persona, per option: deterministic candidates -> stylist.
        # One candidate set per persona (options share the pool — variety
        # comes from the memory/avoid rules, not re-sampling); the seed is
        # fresh per request so re-asking the same prompt re-samples.
        outfits: list[PersonaOutfit] = []
        context: list[str] = []  # first-option summaries for pair coordination

        for persona in personas:
            items = [dict(row) for row in repo.items.list_all(conn, persona_id=persona["id"])]
            candidates = select(
                items, temp_c=temp_c, occasion=occasion, rng_seed=seed,
                activity=activity,
            )
            recent_ids = repo.history.recent_item_ids(conn, persona["id"], limit=RECENT_MEMORY)
            # Variety avoid-set: everything recently suggested to this person
            # (history) plus their earlier options in this same request. The
            # LLM gets these as prompt lines; the deterministic fallback gets
            # them as ids to rotate away from (while a slot has alternatives).
            recent_flat = {i for ids in recent_ids for i in ids}
            sibling_summaries: list[str] = []   # this persona's earlier options
            sibling_ids: list[int] = []          # ...their item ids

            for option in range(1, count + 1):
                persona_outfit, summary = self._dress_one(
                    conn=conn,
                    config=config,
                    city=city,
                    model=model,
                    ollama_url=ollama_url,
                    mood=mood,
                    occasion=occasion,
                    activity=activity,
                    temp_c=temp_c,
                    weather=weather,
                    candidates=candidates,
                    persona=persona,
                    context_outfits=list(context),
                    recent_outfits_ids=recent_ids,
                    sibling_summaries=sibling_summaries,
                    avoid_ids=recent_flat | set(sibling_ids),
                    option=option,
                )
                outfits.append(persona_outfit)
                if summary:
                    sibling_summaries.append(summary)
                    sibling_ids.extend(
                        oi.item.id for oi in persona_outfit.outfit
                    )
                if option == 1 and summary:
                    context.append(summary)  # later personas coordinate with this

        all_gaps = gaps + [g for o in outfits for g in o.gaps]
        first = outfits[0]
        return RecommendResponse(
            title=first.title,
            outfit=first.outfit,
            rationale=first.rationale,
            source=first.source,
            gaps=all_gaps,
            weather=weather,
            history_id=first.history_id,
            outfits=outfits,
        )

    def _dress_one(
        self,
        *,
        conn: sqlite3.Connection,
        config: AppConfig,
        city: str,
        model: str,
        ollama_url: str,
        mood: str,
        occasion: str,
        activity: str | None = None,
        temp_c: float,
        weather: Weather,
        candidates,
        persona: dict,
        context_outfits: list[str],
        recent_outfits_ids: list[list[int]],
        sibling_summaries: list[str],
        avoid_ids: set[int],
        option: int,
    ) -> tuple[PersonaOutfit, str | None]:
        """Run the candidate/stylist pipeline for one persona's one option.

        Returns (outfit, one-line summary for the next stylist call).
        """
        del config, city, temp_c  # kept in signature for symmetry; unused here
        gaps: list[str] = []
        gaps.extend(candidates.gaps)

        # Variety memory: recently suggested outfits (history) and this
        # persona's earlier options in the same request, as one-line
        # summaries for the prompt and as ids for the fallback avoid-set.
        recent_summaries = [
            _outfit_summary(conn, ids) for ids in recent_outfits_ids
        ]
        recent_outfits = recent_summaries + list(sibling_summaries)

        if not candidates.has_required:
            history_id = repo.history.add(
                conn,
                mood=mood,
                occasion=occasion,
                weather=weather.model_dump(),
                item_ids=[],
                rationale=" ".join(gaps),
                source="fallback",
                persona_id=persona["id"],
            )
            return PersonaOutfit(
                persona_id=persona["id"],
                persona_name=persona["name"],
                title="No complete outfit possible",
                outfit=[],
                rationale=(
                    "Your wardrobe can't cover today's conditions: " + " ".join(gaps)
                ),
                source="fallback",
                gaps=gaps,
                history_id=history_id,
                option=option,
            ), None

        # LLM stylist, with deterministic fallback. The persona's free-text
        # description and gender steer the model only — candidates/fallback
        # are unchanged by them. The fallback avoids recently suggested items.
        try:
            choice = stylist.choose(
                provider=self.provider_for(ollama_url),
                model=model,
                candidates=candidates,
                mood=mood,
                occasion=occasion,
                weather=weather,
                context_outfits=context_outfits,
                persona_description=persona.get("description"),
                recent_outfits=recent_outfits or None,
                persona_gender=persona.get("gender"),
                activity=activity,
            )
        except stylist.StylistError:
            choice = stylist.fallback_choice(candidates, avoid=set(avoid_ids))
            gaps.append("Stylist model unavailable or returned an unusable answer; "
                        "showing a safe deterministic pick.")

        # Assemble the outfit in display order. slot_picks keys are pick
        # roles ("layer" = cardigan over the top, "underlayer" = tights
        # under the bottom); each outfit entry keeps the item's broad slot.
        pick_order = ["top", "layer", "bottom", "underlayer", "outerwear", "shoes"]
        wanted_ids = list(choice.slot_picks.values()) + choice.accessory_ids
        by_id = {row["id"]: row for row in repo.items.get_many(conn, wanted_ids)}
        outfit: list[OutfitItem] = []
        for pick_key in pick_order:
            item_id = choice.slot_picks.get(pick_key)
            if item_id is not None and item_id in by_id:
                row = by_id[item_id]
                outfit.append(OutfitItem(slot=row["type"], item=repo.items.to_item(row)))
        for acc_id in choice.accessory_ids:
            if acc_id in by_id:
                outfit.append(OutfitItem(slot="accessory", item=repo.items.to_item(by_id[acc_id])))

        # Log to this persona's history (worn tracking stays per person).
        history_id = repo.history.add(
            conn,
            mood=mood,
            occasion=occasion,
            weather=weather.model_dump(),
            item_ids=[oi.item.id for oi in outfit],
            rationale=choice.rationale,
            source=choice.source,
            persona_id=persona["id"],
        )

        persona_outfit = PersonaOutfit(
            persona_id=persona["id"],
            persona_name=persona["name"],
            title=choice.title,
            outfit=outfit,
            rationale=choice.rationale,
            source=choice.source,
            gaps=gaps,
            history_id=history_id,
            option=option,
        )

        # One line for the next stylist call (sibling options, coordination).
        pieces = ", ".join(
            f"{oi.item.name} ({oi.item.color})" for oi in outfit[:4]
        ) or "nothing yet"
        summary = f"{persona['name']}: {pieces}"
        return persona_outfit, summary
