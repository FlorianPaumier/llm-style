"""API tests for photo classification + image lifecycle through the API.

One photo can yield several drafts (flat-lay); every response carries
`items`, one entry per detected garment with its own photo token.
"""
import io
import json

from app.services import images


def png_bytes(size=64):
    # Minimal valid PNG header; the backend never decodes it.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def upload(client, filename="hoodie.png", content=None, path="/api/classify"):
    return client.post(
        path,
        files={"photo": (filename, io.BytesIO(content if content is not None else png_bytes()), "image/png")},
    )


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
    # The old single-object reply still classifies (one draft).
    return json.dumps(draft_obj())


def drafts_reply(names):
    """A multi-item reply: a JSON array of draft objects."""
    objs = [draft_obj(n) for n in names]
    for obj in objs:
        if "trousers" in obj["name"].lower():
            obj.update(category="jeans", type="bottom")
    return json.dumps(objs)


class TestClassifyApi:
    def test_photo_returns_draft_and_token(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        r = upload(client)
        assert r.status_code == 200, r.text
        body = r.json()
        # A single-object reply still yields exactly one draft — the old
        # single-photo UX (prefilled form) is unchanged.
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["name"] == "Black hoodie"
        assert item["type"] == "top"
        assert item["warmth"] == 3
        # The photo is referenced by an opaque token, not a path.
        assert images.PHOTO_NAME_RE.match(item["photo_token"])
        assert images.photo_path(item["photo_token"]).is_file()

    def test_multi_item_photo_returns_draft_per_item(self, api):
        """A flat-lay reply (JSON array of 2) -> 2 drafts, each with its own
        independently claimable copy of the photo."""
        client, app = api
        from conftest import ScriptedProvider

        payload = b"\x89PNG flatlay"
        provider = ScriptedProvider([drafts_reply(["Navy shirt", "Grey trousers"])])
        app.state.recommender.provider_for = lambda url: provider

        r = upload(client, filename="flatlay.png", content=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 2
        tokens = [d["photo_token"] for d in body["items"]]
        assert tokens[0] != tokens[1]  # one photo per draft
        for draft, name in zip(body["items"], ["Navy shirt", "Grey trousers"]):
            assert draft["name"] == name
            assert images.PHOTO_NAME_RE.match(draft["photo_token"])
            assert images.photo_path(draft["photo_token"]).is_file()
        # Each saved copy is the source photo's bytes.
        for token in tokens:
            assert (images.images_dir() / token).read_bytes() == payload
        # ONE model call for the whole photo.
        assert len(provider.calls) == 1

    def test_invalid_element_dropped_valid_kept(self, api):
        """A reply mixing a bad draft (type "hat") with a good one yields
        only the valid draft — the engine drops unusable elements."""
        client, app = api
        from conftest import ScriptedProvider

        bad = draft_obj("Weird hat")
        bad["type"] = "hat"
        provider = ScriptedProvider([json.dumps([bad, draft_obj("Fine tee")])])
        app.state.recommender.provider_for = lambda url: provider

        r = upload(client)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [d["name"] for d in body["items"]] == ["Fine tee"]

    def test_bad_extension_rejected_before_model(self, api):
        client, _ = api
        r = upload(client, filename="virus.exe")
        assert r.status_code == 422

    def test_empty_upload_rejected(self, api):
        client, _ = api
        r = upload(client, content=b"")
        assert r.status_code == 422

    def test_oversize_upload_rejected(self, api):
        client, _ = api
        r = upload(client, content=b"x" * (images.MAX_IMAGE_BYTES + 1))
        assert r.status_code == 413

    def test_model_down_returns_503(self, api):
        client, app = api

        class Down:
            def complete(self, messages, model, temperature=0.7):
                raise ConnectionError("no ollama")

        app.state.recommender.provider_for = lambda url: Down()
        r = upload(client)
        assert r.status_code == 503

    def test_async_classify_job(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        r = upload(client, path="/api/classify/async")
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st["status"] in ("done", "failed"):
                break
        assert st["status"] == "done", st
        # The async photo is reported like a one-file bulk job: one
        # ok:true row per draft, carrying the upload's filename.
        rows = st["result"]
        assert len(rows) == 1
        assert rows[0]["ok"] is True
        assert rows[0]["filename"] == "hoodie.png"
        assert rows[0]["draft"]["name"] == "Black hoodie"
        assert images.PHOTO_NAME_RE.match(rows[0]["draft"]["photo_token"])

    def test_async_single_photo_multi_draft_rows(self, api):
        """Async photo with 2 drafts -> a done job with 2 ok:true rows
        (same filename, distinct draft tokens)."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([drafts_reply(["Shirt A", "Shirt B"])])
        app.state.recommender.provider_for = lambda url: provider

        r = upload(client, filename="two.png", path="/api/classify/async")
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st["status"] in ("done", "failed"):
                break
        assert st["status"] == "done", st
        rows = st["result"]
        assert len(rows) == 2
        tokens = []
        for row, name in zip(rows, ["Shirt A", "Shirt B"]):
            assert row["ok"] is True
            assert row["filename"] == "two.png"
            assert row["draft"]["name"] == name
            tokens.append(row["draft"]["photo_token"])
        assert tokens[0] != tokens[1]
        for token in tokens:
            assert images.PHOTO_NAME_RE.match(token)
            assert images.photo_path(token).is_file()


class TestItemPhotoLifecycle:
    def test_create_claims_draft_and_delete_cleans_up(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        body = upload(client).json()
        token = body["items"][0]["photo_token"]

        # Save the item with the draft photo attached.
        r = client.post(
            "/api/items",
            json={
                "name": body["items"][0]["name"],
                "category": body["items"][0]["category"],
                "type": body["items"][0]["type"],
                "color": body["items"][0]["color"],
                "warmth": body["items"][0]["warmth"],
                "formality": body["items"][0]["formality"],
                "style_tags": body["items"][0]["style_tags"],
                "photo_token": token,
            },
        )
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["has_photo"] is True
        assert item["photo_url"] == f"/api/items/{item['id']}/photo"
        assert not images.photo_path(token).exists()  # draft renamed away

        # Photo is served.
        pr = client.get(f"/api/items/{item['id']}/photo")
        assert pr.status_code == 200
        assert pr.content == png_bytes()

        # Deleting the item removes the photo file too.
        assert client.delete(f"/api/items/{item['id']}").status_code == 204
        assert client.get(f"/api/items/{item['id']}/photo").status_code == 404
        assert not (images.images_dir() / f"{item['id']}.png").exists()

    def test_multi_drafts_claimable_independently(self, api):
        """Both drafts from one photo can be saved; each claims its own
        copy of the bytes without disturbing the other."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([drafts_reply(["Navy shirt", "Grey trousers"])])
        app.state.recommender.provider_for = lambda url: provider

        body = upload(client).json()
        saved = []
        for draft in body["items"]:
            r = client.post(
                "/api/items",
                json={
                    "name": draft["name"],
                    "category": draft["category"],
                    "type": draft["type"],
                    "warmth": draft["warmth"],
                    "formality": draft["formality"],
                    "photo_token": draft["photo_token"],
                },
            )
            assert r.status_code == 201, r.text
            saved.append(r.json())
        # Both items exist with their own photos, and every draft token
        # has been claimed (renamed away).
        assert [i["has_photo"] for i in saved] == [True, True]
        for item in saved:
            assert client.get(item["photo_url"]).status_code == 200
        assert list(images.images_dir().glob("draft-*")) == []

    def test_unknown_token_rejected(self, api):
        client, _ = api
        r = client.post(
            "/api/items",
            json={"name": "T", "category": "t_shirt", "type": "top",
                  "warmth": 1, "formality": 1,
                  "photo_token": "draft-000000000000.png"},
        )
        assert r.status_code == 422

    def test_attach_photo_to_existing_item(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft(), good_draft()])
        app.state.recommender.provider_for = lambda url: provider

        item = client.post(
            "/api/items",
            json={"name": "Hoodie", "category": "hoodie", "type": "top",
                  "warmth": 3, "formality": 1},
        ).json()

        body = upload(client).json()
        r = client.post(
            f"/api/items/{item['id']}/photo", json={"photo_token": body["items"][0]["photo_token"]}
        )
        assert r.status_code == 201, r.text
        assert r.json()["has_photo"] is True

        # Replacing the photo swaps the file cleanly.
        body2 = upload(client, content=b"\x89PNG second").json()
        r2 = client.post(
            f"/api/items/{item['id']}/photo", json={"photo_token": body2["items"][0]["photo_token"]}
        )
        assert r2.status_code == 201
        assert client.get(f"/api/items/{item['id']}/photo").content == b"\x89PNG second"

    def test_photo_404_for_item_without_photo(self, api):
        client, _ = api
        r = client.post(
            "/api/items",
            json={"name": "Plain tee", "category": "t_shirt", "type": "top",
                  "warmth": 1, "formality": 1},
        )
        item_id = r.json()["id"]
        assert client.get(f"/api/items/{item_id}/photo").status_code == 404

    def test_stored_path_can_never_leak_files(self, api):
        """The photo route resolves only names matching the strict photo
        pattern inside the images dir — /etc/hosts is unreachable even if
        the DB row somehow holds it."""
        client, _ = api
        item = client.post(
            "/api/items",
            json={"name": "X", "category": "t_shirt", "type": "top",
                  "warmth": 1, "formality": 1},
        ).json()
        # Tamper directly with the DB to simulate a corrupted row.
        import sqlite3
        from app.db import connect
        conn = connect(images.IMAGES_DIR.parent / "api.db")
        conn.execute(
            "UPDATE items SET image_path = '/etc/hosts' WHERE id = ?", (item["id"],)
        )
        conn.commit()
        conn.close()
        assert client.get(f"/api/items/{item['id']}/photo").status_code == 404


class TestSettingsVisionModel:
    def test_settings_include_vision_model_default(self, api):
        client, _ = api
        r = client.get("/api/settings").json()
        assert r["vision_model"] == "gemma3:4b"

    def test_settings_update_vision_model(self, api):
        client, _ = api
        r = client.put("/api/settings", json={"vision_model": "llava:7b"}).json()
        assert r["vision_model"] == "llava:7b"
        assert client.get("/api/settings").json()["vision_model"] == "llava:7b"
