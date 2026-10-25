"""Tests for the LLM stylist: JSON extraction, validation, retry, fallback."""
import json

import pytest

from app.llm.provider import extract_json
from app.services import stylist
from app.services.candidates import select

from conftest import ScriptedProvider, full_wardrobe, make_item

SEED = 20260903
CANDIDATES = select(full_wardrobe(), temp_c=18.0, occasion="casual", rng_seed=SEED)


def valid_reply():
    return json.dumps(
        {
            "title": "Chill navy day",
            "item_ids": {
                "top": CANDIDATES.slots["top"][0]["id"],
                "bottom": CANDIDATES.slots["bottom"][0]["id"],
                "shoes": CANDIDATES.slots["shoes"][0]["id"],
                "outerwear": None,
                "accessories": [],
            },
            "rationale": "Soft tones echo your relaxed mood.",
        }
    )


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_prose_around_it(self):
        assert extract_json('Sure! Here you go: {"a": {"b": 2}} hope it helps') == {
            "a": {"b": 2}
        }

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError):
            extract_json("I cannot do that")


class TestChoose:
    def test_valid_answer_passes(self):
        provider = ScriptedProvider([valid_reply()])
        choice = stylist.choose(provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual")
        assert choice.source == "llm"
        assert choice.title == "Chill navy day"
        assert set(choice.slot_picks) >= {"top", "bottom", "shoes"}

    def test_invalid_then_valid_retries_once(self):
        bad = json.dumps({"title": "x", "item_ids": {"top": 999999}})
        provider = ScriptedProvider([bad, valid_reply()])
        choice = stylist.choose(provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual")
        assert choice.source == "llm"
        assert len(provider.calls) == 2
        # The retry prompt must tell the model what was wrong.
        assert "invalid" in provider.calls[1][-1]["content"].lower()

    def test_two_bad_answers_raise_for_fallback(self):
        bad = json.dumps({"title": "x", "item_ids": {}})
        provider = ScriptedProvider([bad, bad])
        with pytest.raises(stylist.StylistError):
            stylist.choose(provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual")

    def test_network_error_raises_immediately(self):
        import httpx

        provider = ScriptedProvider([httpx.ConnectError("ollama down")])
        with pytest.raises(stylist.StylistError):
            stylist.choose(provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual")

    def test_empty_required_slots_skip_model_call(self):
        from app.services.candidates import CandidateSet

        empty = CandidateSet(slots={"top": CANDIDATES.slots["top"]}, temp_c=18.0)
        provider = ScriptedProvider([])
        with pytest.raises(stylist.StylistError):
            stylist.choose(provider, "dolphin-mistral:7b", empty, "chill", "casual")
        assert provider.calls == []  # never called the model

    def test_unknown_ids_rejected(self):
        reply = json.dumps(
            {
                "title": "Bad",
                "item_ids": {
                    "top": CANDIDATES.slots["top"][0]["id"] + 5000,
                    "bottom": CANDIDATES.slots["bottom"][0]["id"],
                    "shoes": CANDIDATES.slots["shoes"][0]["id"],
                },
                "rationale": "x",
            }
        )
        provider = ScriptedProvider([reply, reply])
        with pytest.raises(stylist.StylistError):
            stylist.choose(provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual")


class TestFallback:
    def test_fallback_picks_closest_formality_per_slot(self):
        cs = select(full_wardrobe(), temp_c=5.0, occasion="formal", rng_seed=SEED)
        choice = stylist.fallback_choice(cs)
        assert choice.source == "fallback"
        assert set(choice.slot_picks) == {"top", "bottom", "shoes", "outerwear"}
        # Every picked item should be within one formality point of the target 5.
        by_id = {it["id"]: it for its in cs.slots.values() for it in its}
        for slot, item_id in choice.slot_picks.items():
            assert by_id[item_id]["formality"] >= 4

    def test_fallback_skips_accessory_wrong_for_the_temperature(self):
        # 30°C day (warmth band 1-1), only candidate is a warmth-4 beanie:
        # the fallback must not include it — no wool scarf in July.
        cs = select(
            [make_item(1, "top", 1, 2), make_item(2, "bottom", 1, 2),
             make_item(3, "shoes", 1, 2), make_item(4, "accessory", 4, 2)],
            temp_c=30.0, occasion="casual", rng_seed=SEED,
        )
        choice = stylist.fallback_choice(cs)
        assert choice.accessory_ids == []

    def test_fallback_includes_band_matching_accessory(self):
        # 5°C day (warmth band 3-4): the warmth-4 beanie fits and is picked
        # even though a warmth-1 watch also sits in the candidate list.
        cs = select(
            [make_item(1, "top", 4, 2), make_item(2, "bottom", 4, 2),
             make_item(3, "shoes", 4, 2), make_item(4, "accessory", 1, 2),
             make_item(5, "accessory", 4, 2)],
            temp_c=5.0, occasion="casual", rng_seed=SEED,
        )
        choice = stylist.fallback_choice(cs)
        assert choice.accessory_ids == [5]


class TestPrompt:
    def test_prompt_contains_context_and_candidates(self):
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "dreamy" in p
        assert "work" in p
        assert "id 1" in p  # candidate lines present

    def test_prompt_requires_a_finished_coordinated_outfit(self):
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "one finished look" in p
        assert "not a collection of individually suitable pieces" in p
        assert "top + bottom + shoes" in p
        assert "colours and formality work together" in p
        assert "cold, wet, or windy" in p

    def test_prompt_includes_full_weather(self):
        from app.models import Weather

        w = Weather(
            city="Paris", temperature_c=8.0, apparent_temperature_c=5.0,
            precipitation_mm=2.5, wind_speed_kmh=30.0, weather_code=61,
            fetched_at="2026-01-01T00:00:00+00:00",
        )
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work", weather=w)
        # The stylist now sees feels-like, rain and wind, not just temperature.
        assert "8°C" in p
        assert "feels like 5°C" in p
        assert "rain expected" in p
        assert "wind 30 km/h" in p

    def test_prompt_with_persona_description(self):
        p = stylist.build_prompt(
            CANDIDATES, mood="dreamy", occasion="work",
            persona_description="no hats — they don't suit me",
        )
        assert "no hats — they don't suit me" in p
        assert "Notes about this person" in p
        assert "respect these preferences" in p
        # The line sits in the Today's context block, before the candidates.
        assert p.index("Notes about this person") < p.index("Candidate items")

    def test_prompt_without_persona_description_has_no_notes_line(self):
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "Notes about this person" not in p
        assert "respect these preferences" not in p
        # Explicit None and blank strings behave like absent.
        for missing in (None, "", "   "):
            p = stylist.build_prompt(
                CANDIDATES, mood="dreamy", occasion="work",
                persona_description=missing,
            )
            assert "Notes about this person" not in p

    def test_choose_passes_description_to_prompt(self):
        provider = ScriptedProvider([valid_reply()])
        stylist.choose(
            provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual",
            persona_description="prefers bold colors",
        )
        user_msg = provider.calls[0][-1]["content"]
        assert "prefers bold colors" in user_msg
        assert "respect these preferences" in user_msg


    def test_prompt_with_persona_gender(self):
        p = stylist.build_prompt(
            CANDIDATES, mood="dreamy", occasion="work", persona_gender="female"
        )
        assert "This person is a woman" in p
        assert "silhouettes" in p
        # The gender note sits in the Today's context block, before the
        # candidates.
        assert p.index("This person is a woman") < p.index("Candidate items")

        p = stylist.build_prompt(
            CANDIDATES, mood="dreamy", occasion="work", persona_gender="male"
        )
        assert "This person is a man" in p

    def test_prompt_without_gender_has_no_note(self):
        for missing in (None, "unspecified"):
            p = stylist.build_prompt(
                CANDIDATES, mood="dreamy", occasion="work", persona_gender=missing
            )
            assert "This person is" not in p

    def test_prompt_with_activity(self):
        p = stylist.build_prompt(
            CANDIDATES, mood="dreamy", occasion="smart",
            activity="Company Christmas dinner",
        )
        assert 'What they\'ll be doing: "Company Christmas dinner"' in p
        # The rule tells the model to dress for the activity and to add a
        # warm layer for dinners/events.
        assert "dress for the" in p
        assert "warm layer" in p
        # The activity sits in Today's context, before the candidates.
        assert p.index("What they'll be doing") < p.index("Candidate items")

    def test_prompt_without_activity_has_no_activity_line(self):
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "What they'll be doing" not in p
        assert "warm layer" not in p

    def test_choose_passes_activity_to_prompt(self):
        provider = ScriptedProvider([valid_reply()])
        stylist.choose(
            provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual",
            activity="zoo day",
        )
        user_msg = provider.calls[0][-1]["content"]
        assert 'What they\'ll be doing: "zoo day"' in user_msg

    def test_choose_passes_gender_to_prompt(self):
        provider = ScriptedProvider([valid_reply()])
        stylist.choose(
            provider, "dolphin-mistral:7b", CANDIDATES, "chill", "casual",
            persona_gender="male",
        )
        user_msg = provider.calls[0][-1]["content"]
        assert "This person is a man" in user_msg


class TestAccessoryGuidance:
    def test_prompt_tells_model_accessories_are_optional_per_context(self):
        # The rules line must let the model judge accessories per weather,
        # occasion and persona notes — not treat them as always-on.
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "at most 2 accessories" in p
        assert "skip" in p and "accessories" in p
        for keyword in ("weather", "occasion", "notes"):
            assert keyword in p.split("Rules:")[-1]

    def test_validate_still_caps_accessories_at_two(self):
        # The mobile contract caps accessories at 2; _validate truncates
        # even when the model greedily lists every candidate.
        from app.services.candidates import CandidateSet

        cs = CandidateSet(
            slots={
                "top": CANDIDATES.slots["top"],
                "bottom": CANDIDATES.slots["bottom"],
                "shoes": CANDIDATES.slots["shoes"],
                # 3+ accessory candidates so a greedy reply can be crafted.
                "accessory": full_wardrobe()[-6:],
            },
            temp_c=18.0,
        )
        acc_ids = [it["id"] for it in cs.slots["accessory"]]
        assert len(acc_ids) >= 3
        reply = json.dumps(
            {
                "title": "Loaded",
                "item_ids": {
                    "top": cs.slots["top"][0]["id"],
                    "bottom": cs.slots["bottom"][0]["id"],
                    "shoes": cs.slots["shoes"][0]["id"],
                    "accessories": acc_ids,
                },
                "rationale": "Why not all of it.",
            }
        )
        provider = ScriptedProvider([reply])
        choice = stylist.choose(provider, "dolphin-mistral:7b", cs, "chill", "casual")
        assert len(choice.accessory_ids) == 2
