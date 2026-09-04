"""Tests for the LLM stylist: JSON extraction, validation, retry, fallback."""
import json

import pytest

from app.llm.provider import extract_json
from app.services import stylist
from app.services.candidates import select

from conftest import ScriptedProvider, full_wardrobe

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


class TestPrompt:
    def test_prompt_contains_context_and_candidates(self):
        p = stylist.build_prompt(CANDIDATES, mood="dreamy", occasion="work")
        assert "dreamy" in p
        assert "work" in p
        assert "id 1" in p  # candidate lines present
