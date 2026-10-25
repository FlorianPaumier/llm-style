"""API tests for quick add: photo -> saved items, no review form.

One photo can yield several items (flat-lay): every detected garment is
saved, each claiming its own copy of the photo bytes.
"""
import io
import json

from app.services import images


def png_bytes(size=64):
    # Minimal valid PNG header; the backend never decodes it.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def draft_obj(name="Black hoodie"):
    return {
        "name": name,
        "category": "hoodie",
        "type": "top",
        "color": "black",
        "warmth": 3,
        "formality": 1,
        "style_tags": "streetwear, cosy",
    }


def good_draft():
    # The old single-object reply still quick-adds (one item).
    return json.dumps(draft_obj())


def drafts_reply(names):
    """A multi-item reply: a JSON array of draft objects."""
    objs = [draft_obj(n) for n in names]
    for obj in objs:
        if "trousers" in obj["name"].lower():
            obj.update(category="jeans", type="bottom")
    return json.dumps(objs)


def quick_add(client, filename="hoodie.png", content=None, persona_id=None):
    """POST a photo (optionally with persona_id) to the quick-add route."""
    files = {
        "photo": (
            filename,
            io.BytesIO(content if content is not None else png_bytes()),
            "image/png",
        )
    }
    data = {"persona_id": str(persona_id)} if persona_id is not None else None
    return client.post("/api/items/from-photo", files=files, data=data)


class TestQuickAdd:
    def test_photo_becomes_saved_item(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        r = quick_add(client)
        assert r.status_code == 201, r.text
        body = r.json()
        # A single-object reply saves exactly one item — the old flow.
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["name"] == "Black hoodie"
        assert item["type"] == "top"
        assert item["warmth"] == 3
        assert item["has_photo"] is True
        assert item["photo_url"] == f"/api/items/{item['id']}/photo"
        assert item["persona_id"] == 1  # default = first persona

        # The photo is served back and the draft token is gone (claimed).
        pr = client.get(f"/api/items/{item['id']}/photo")
        assert pr.status_code == 200
        assert pr.content == png_bytes()
        drafts = list(images.images_dir().glob("draft-*"))
        assert drafts == []

        # The item shows up in the default persona's wardrobe.
        listing = client.get("/api/items").json()
        assert [i["id"] for i in listing["items"]] == [item["id"]]

    def test_flat_lay_saves_every_item(self, api):
        """A 2-item photo -> 201 with 2 saved items, each with its own copy
        of the photo, filed under the requested persona."""
        client, app = api
        from conftest import ScriptedProvider

        persona = client.post("/api/personas", json={"name": "Alex"}).json()
        provider = ScriptedProvider([drafts_reply(["Navy shirt", "Grey trousers"])])
        app.state.recommender.provider_for = lambda url: provider

        payload = b"\x89PNG flatlay"
        r = quick_add(client, filename="flatlay.png", content=payload, persona_id=persona["id"])
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["items"]) == 2
        assert [i["name"] for i in body["items"]] == ["Navy shirt", "Grey trousers"]
        for item in body["items"]:
            assert item["has_photo"] is True
            assert item["persona_id"] == persona["id"]
            # Each item serves the SAME source bytes (copied per item).
            pr = client.get(f"/api/items/{item['id']}/photo")
            assert pr.status_code == 200
            assert pr.content == payload
        # Every token was claimed — no draft leftovers.
        assert list(images.images_dir().glob("draft-*")) == []
        # Both items appear in the persona's wardrobe.
        listing = client.get(f"/api/items?persona_id={persona['id']}").json()
        assert [i["id"] for i in listing["items"]] == [i["id"] for i in body["items"]]

    def test_with_persona_id(self, api):
        client, app = api
        from conftest import ScriptedProvider

        persona = client.post("/api/personas", json={"name": "Alex"}).json()
        provider = ScriptedProvider([good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        r = quick_add(client, persona_id=persona["id"])
        assert r.status_code == 201, r.text
        assert r.json()["items"][0]["persona_id"] == persona["id"]

    def test_unknown_persona_rejected(self, api):
        client, _ = api
        r = quick_add(client, persona_id=999)
        assert r.status_code == 422
        assert "Unknown persona id 999" in r.json()["detail"]

    def test_bad_extension_rejected(self, api):
        client, _ = api
        r = quick_add(client, filename="virus.exe")
        assert r.status_code == 422

    def test_oversize_rejected(self, api):
        client, _ = api
        r = quick_add(client, content=b"x" * (images.MAX_IMAGE_BYTES + 1))
        assert r.status_code == 413

    def test_model_down_returns_503(self, api):
        client, app = api

        class Down:
            def complete(self, messages, model, temperature=0.7):
                raise ConnectionError("no ollama")

        app.state.recommender.provider_for = lambda url: Down()
        r = quick_add(client)
        assert r.status_code == 503
        assert "Vision model unavailable" in r.json()["detail"]

    def test_partially_invalid_draft_saves_only_valid_one(self, api):
        """One draft fails ItemIn's max_length, the other is fine: the
        good one is saved, the bad one skipped — and the invalid draft's
        photo copy never hits disk (no orphan draft files)."""
        client, app = api
        from conftest import ScriptedProvider

        bad = draft_obj("Fine tee")
        bad["name"] = "x" * 150  # classify passes it; ItemIn's max_length fails
        good = draft_obj("Navy hoodie")
        provider = ScriptedProvider([json.dumps([bad, good])])
        app.state.recommender.provider_for = lambda url: provider

        r = quick_add(client)
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["name"] == "Navy hoodie"
        assert item["has_photo"] is True

        # The images dir holds exactly the one claimed file — no orphan
        # draft-*.png for the rejected draft, nothing else.
        files_on_disk = sorted(p.name for p in images.images_dir().iterdir())
        assert files_on_disk == [f"{item['id']}.png"]

    def test_all_drafts_invalid_returns_503_and_saves_nothing(self, api):
        """Every draft in the reply fails ItemIn validation -> ValueError
        -> 503; no item and no draft photo ever hit disk."""
        client, app = api
        from conftest import ScriptedProvider

        bad_a = draft_obj()
        bad_a["name"] = "x" * 150
        bad_b = draft_obj()
        bad_b["name"] = "y" * 150
        provider = ScriptedProvider([json.dumps([bad_a, bad_b])])
        app.state.recommender.provider_for = lambda url: provider

        r = quick_add(client)
        assert r.status_code == 503
        assert "Vision model returned unusable output" in r.json()["detail"]
        assert client.get("/api/items").json()["total"] == 0
        assert list(images.images_dir().glob("draft-*")) == []

    def test_unusable_draft_returns_503_and_saves_nothing(self, api):
        client, app = api
        from conftest import ScriptedProvider

        # Two bad replies: classify retries once, then raises
        # ClassificationError("model failed twice: ...").
        provider = ScriptedProvider(["not json at all", "still not json"])
        app.state.recommender.provider_for = lambda url: provider

        r = quick_add(client)
        assert r.status_code == 503
        assert "Vision model unavailable" in r.json()["detail"]
        # Nothing was saved and no draft photo was left behind.
        assert client.get("/api/items").json()["total"] == 0
        assert list(images.images_dir().glob("draft-*")) == []
