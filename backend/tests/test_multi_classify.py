"""Multi-item photo classification: one photo -> many wardrobe-item drafts.

classify_multi drives the whole batch: parse the model's reply as a
top-level array (a lone object still works — one-element list), drop
elements that fail _validate, retry once when nothing valid comes back,
and truncate at 8 items.
"""
import json

import pytest

from app.llm.provider import extract_json_multi
from app.services import classify

from conftest import ScriptedProvider

FAKE_B64 = "aGVsbG8="  # "hello" — the fake provider never decodes it


def draft_obj(name="Navy linen shirt", type="top", warmth=1, formality=3, category=None):
    # The model returns category (the detailed field); the broad type must
    # agree with it. Defaults pair the two so replies stay valid.
    if category is None:
        category = {
            "top": "t_shirt", "bottom": "jeans", "shoes": "sneakers",
            "outerwear": "denim_jacket", "accessory": "scarf",
        }.get(type, "t_shirt")
    return {
        "name": name,
        "category": category,
        "type": type,
        "color": "navy",
        "warmth": warmth,
        "formality": formality,
        "style_tags": "summer, smart-casual",
    }


def array_reply(*objs):
    return json.dumps(list(objs))


class TestExtractJsonMulti:
    def test_plain_array(self):
        reply = '[{"name": "a"}, {"name": "b"}]'
        assert extract_json_multi(reply) == [
            {"name": "a"},
            {"name": "b"},
        ]

    def test_fenced_array(self):
        reply = '```json\n[{"a": 1}, {"b": 2}]\n```'
        assert extract_json_multi(reply) == [{"a": 1}, {"b": 2}]

    def test_single_object_becomes_one_element_list(self):
        reply = '{"name": "Navy linen shirt", "warmth": 1}'
        assert extract_json_multi(reply) == [{"name": "Navy linen shirt", "warmth": 1}]

    def test_fenced_single_object(self):
        reply = '```json\n{"a": 1}\n```'
        assert extract_json_multi(reply) == [{"a": 1}]

    def test_prose_with_no_brackets_raises_value_error(self):
        # Bare prose (no fence, no leading { or [) is an error — unlike
        # extract_json, which brace-searches anywhere in the text.
        with pytest.raises(ValueError):
            extract_json_multi('Sure! Here you go: {"a": 1} hope it helps')

    def test_prose_around_fenced_array_still_works(self):
        reply = 'Sure! Here: ```json\n[{"a": 1}]\n``` hope it helps'
        assert extract_json_multi(reply) == [{"a": 1}]

    def test_empty_array(self):
        assert extract_json_multi("[]") == []

    def test_garbage_raises_value_error(self):
        for bad in ("I cannot do that", "", "no braces at all"):
            with pytest.raises(ValueError):
                extract_json_multi(bad)

    def test_non_dict_elements_raise_value_error(self):
        with pytest.raises(ValueError):
            extract_json_multi('["top", 3, null]')

    def test_mixed_elements_raise_value_error(self):
        with pytest.raises(ValueError):
            extract_json_multi('[{"a": 1}, "not an object"]')

    def test_unbalanced_array_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_json_multi('[{"a": 1}, {"b": 2}')


class TestClassifyMultiHappyPaths:
    def test_array_reply_returns_draft_per_item_order_preserved(self):
        provider = ScriptedProvider(
            [
                array_reply(
                    draft_obj("Navy linen shirt"),
                    draft_obj("Grey wool trousers", type="bottom"),
                    draft_obj("White sneakers", type="shoes"),
                )
            ]
        )
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == [
            "Navy linen shirt",
            "Grey wool trousers",
            "White sneakers",
        ]
        assert [d.type for d in drafts] == ["top", "bottom", "shoes"]

    def test_single_object_reply_returns_one_element_list(self):
        provider = ScriptedProvider([json.dumps(draft_obj())])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert len(drafts) == 1
        assert drafts[0].name == "Navy linen shirt"

    def test_fenced_array_reply_with_prose(self):
        reply = (
            "Sure! Here are the items: ```json\n"
            + array_reply(draft_obj("Navy linen shirt"),
                         draft_obj("Grey wool trousers", type="bottom"))
            + "\n``` hope that helps"
        )
        provider = ScriptedProvider([reply])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == ["Navy linen shirt", "Grey wool trousers"]

    def test_message_carries_image_and_temperature(self):
        provider = ScriptedProvider([json.dumps(draft_obj())])
        classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        sent = provider.calls[0]
        assert sent[1]["images"] == [FAKE_B64]


class TestClassifyMultiDropsInvalidElements:
    def test_bad_warmth_element_dropped_others_kept(self):
        bad = draft_obj("Broken tee")
        bad["warmth"] = 9
        provider = ScriptedProvider(
            [
                array_reply(
                    draft_obj("Navy linen shirt"),
                    bad,
                    draft_obj("Grey wool trousers", type="bottom"),
                )
            ]
        )
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == ["Navy linen shirt", "Grey wool trousers"]

    def test_bad_type_element_dropped_others_kept(self):
        bad = draft_obj("Weird hat")
        bad["type"] = "hat"
        provider = ScriptedProvider([array_reply(bad, draft_obj("Fine tee"))])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == ["Fine tee"]

    def test_all_invalid_then_valid_retries_once(self):
        bad = draft_obj("Broken tee")
        bad["warmth"] = 9
        provider = ScriptedProvider([array_reply(bad), json.dumps(draft_obj())])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == ["Navy linen shirt"]
        assert len(provider.calls) == 2

    def test_all_invalid_twice_raises_classification_error(self):
        bad = draft_obj("Broken tee")
        bad["type"] = "spacesuit"
        provider = ScriptedProvider([array_reply(bad), array_reply(bad)])
        with pytest.raises(classify.ClassificationError):
            classify.classify_multi(provider, "gemma3:4b", FAKE_B64)

    def test_empty_array_twice_raises_no_wearable_items_error(self):
        """Two zero-item attempts end in the contract's distinct message."""
        provider = ScriptedProvider(["[]", "[]"])
        with pytest.raises(classify.ClassificationError) as excinfo:
            classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert str(excinfo.value) == "model found no wearable items"

    def test_all_invalid_twice_raises_no_wearable_items_error(self):
        """Every element failing validation is also a zero-items outcome."""
        bad = draft_obj("Broken tee")
        bad["type"] = "spacesuit"
        provider = ScriptedProvider([array_reply(bad), array_reply(bad)])
        with pytest.raises(classify.ClassificationError) as excinfo:
            classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert str(excinfo.value) == "model found no wearable items"

    def test_retry_messages_append_reply_and_error(self):
        """The correction exchange mirrors the single-item pattern:
        assistant reply + user correction, both appended on retry."""
        bad = draft_obj("Broken tee")
        bad["warmth"] = 9
        bad_reply = array_reply(bad)
        provider = ScriptedProvider([bad_reply, json.dumps(draft_obj())])
        classify.classify_multi(provider, "gemma3:4b", FAKE_B64)

        second = provider.calls[1]
        # Original system + image message, then the assistant reply...
        assert second[0]["role"] == "system"
        assert second[1]["role"] == "user"
        assert second[1]["images"] == [FAKE_B64]
        assert second[2] == {"role": "assistant", "content": bad_reply}
        # ...then the user correction quoting the error.
        correction = second[3]["content"]
        assert second[3]["role"] == "user"
        assert "invalid" in correction.lower()
        assert "warmth" in correction  # the specific failure is named

    def test_empty_array_then_valid_array_retries_to_one_item(self):
        provider = ScriptedProvider(
            ["[]", array_reply(draft_obj("Navy linen shirt"))]
        )
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert [d.name for d in drafts] == ["Navy linen shirt"]
        assert len(provider.calls) == 2


class TestClassifyMultiTruncation:
    @pytest.mark.parametrize("count", [10, 9])
    def test_arrays_beyond_eight_are_truncated(self, count):
        reply = array_reply(*[draft_obj(f"Item {i}") for i in range(count)])
        provider = ScriptedProvider([reply])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert len(drafts) == 8
        # Truncation keeps the FIRST eight, order preserved.
        assert [d.name for d in drafts] == [f"Item {i}" for i in range(8)]

    def test_eight_item_array_not_truncated(self):
        reply = array_reply(*[draft_obj(f"Item {i}") for i in range(8)])
        provider = ScriptedProvider([reply])
        drafts = classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        assert len(drafts) == 8


class TestClassifyMultiErrors:
    def test_network_error_raises_classification_error(self):
        import httpx

        provider = ScriptedProvider([httpx.ConnectError("down")])
        with pytest.raises(classify.ClassificationError):
            classify.classify_multi(provider, "gemma3:4b", FAKE_B64)

    def test_garbage_reply_then_garbage_reply_raises(self):
        provider = ScriptedProvider(["I cannot do that", "still no json"])
        with pytest.raises(classify.ClassificationError):
            classify.classify_multi(provider, "gemma3:4b", FAKE_B64)

    def test_old_classify_function_is_gone(self):
        assert not hasattr(classify, "classify")


class TestPrompts:
    def test_user_prompt_describes_array_shape_and_every_item_rule(self):
        provider = ScriptedProvider([json.dumps(draft_obj())])
        classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        user_text = provider.calls[0][1]["content"]

        # The array shape instruction and multi-item rules are present...
        assert "ARRAY of objects" in user_text
        assert "every distinct wearable item" in user_text.lower()
        assert "hangers" in user_text  # non-wearables are ignored
        assert "at most 8" in user_text.lower()

    def test_old_single_item_wording_is_gone(self):
        provider = ScriptedProvider([json.dumps(draft_obj())])
        classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        system_text = provider.calls[0][0]["content"]
        user_text = provider.calls[0][1]["content"]

        for text in (system_text, user_text):
            assert "exactly one item" not in text.lower()
            assert "one clothing item" not in text.lower()

    def test_system_prompt_keeps_judgment_guidance(self):
        provider = ScriptedProvider([json.dumps(draft_obj())])
        classify.classify_multi(provider, "gemma3:4b", FAKE_B64)
        system_text = provider.calls[0][0]["content"]

        assert "charcoal grey" in system_text
        assert "summer tee" in system_text
        assert "black tie" in system_text
        assert "JSON only" in system_text
