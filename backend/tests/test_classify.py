"""Tests for the photo -> draft item classification service."""
import json

import pytest

from app.services import classify

from conftest import ScriptedProvider

FAKE_B64 = "aGVsbG8="  # "hello" — the fake provider never decodes it

GOOD = json.dumps(
    {
        "name": "Navy linen shirt",
        "type": "top",
        "color": "navy",
        "warmth": 1,
        "formality": 3,
        "style_tags": "summer, smart-casual",
    }
)


class TestValidate:
    def test_accepts_good_draft(self):
        draft = classify._validate(json.loads(GOOD))
        assert draft.name == "Navy linen shirt"
        assert draft.type == "top"
        assert draft.warmth == 1 and draft.formality == 3

    def test_rejects_unknown_type(self):
        raw = json.loads(GOOD)
        raw["type"] = "hat"
        with pytest.raises(ValueError):
            classify._validate(raw)

    def test_rejects_out_of_range_scores(self):
        for field, bad in [("warmth", 9), ("formality", 0), ("warmth", "3")]:
            raw = json.loads(GOOD)
            raw[field] = bad
            with pytest.raises(ValueError):
                classify._validate(raw)

    def test_rejects_blank_name(self):
        raw = json.loads(GOOD)
        raw["name"] = "   "
        with pytest.raises(ValueError):
            classify._validate(raw)

    def test_null_optional_fields_become_none(self):
        raw = json.loads(GOOD)
        raw["color"] = None
        raw["style_tags"] = None
        draft = classify._validate(raw)
        assert draft.color is None
        assert draft.style_tags is None


class TestClassify:
    def test_valid_reply_passes_through(self):
        provider = ScriptedProvider([GOOD])
        draft = classify.classify(provider, "gemma3:4b", FAKE_B64)
        assert draft.name == "Navy linen shirt"
        # The message must carry the image for the vision model.
        sent = provider.calls[0]
        assert sent[1]["images"] == [FAKE_B64]

    def test_invalid_then_valid_retries_once(self):
        bad = json.dumps({"name": "x", "type": "spacesuit"})
        provider = ScriptedProvider([bad, GOOD])
        draft = classify.classify(provider, "gemma3:4b", FAKE_B64)
        assert draft.name == "Navy linen shirt"
        assert len(provider.calls) == 2
        assert "invalid" in provider.calls[1][-1]["content"].lower()

    def test_two_failures_raise_classification_error(self):
        bad = json.dumps({"name": "x", "type": "spacesuit"})
        provider = ScriptedProvider([bad, bad])
        with pytest.raises(classify.ClassificationError):
            classify.classify(provider, "gemma3:4b", FAKE_B64)

    def test_network_error_raises_classification_error(self):
        import httpx

        provider = ScriptedProvider([httpx.ConnectError("down")])
        with pytest.raises(classify.ClassificationError):
            classify.classify(provider, "gemma3:4b", FAKE_B64)
