"""API tests for photo classification + image lifecycle through the API."""
import io
import json

from app.services import images


def png_bytes(size=64):
    # Minimal valid PNG header; the backend never decodes it.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def upload(client, filename="hoodie.png", content=None):
    return client.post(
        "/api/classify",
        files={"photo": (filename, io.BytesIO(content or png_bytes()), "image/png")},
    )


def good_draft():
    return json.dumps(
        {
            "name": "Black hoodie",
            "type": "top",
            "color": "black",
            "warmth": 3,
            "formality": 1,
            "style_tags": "streetwear, cosy",
        }
    )


class TestClassifyApi:
    def test_photo_returns_draft_and_saves_image(self, api, monkeypatch, tmp_path):
        client, app = api
        monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")

        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender._provider = lambda url: provider

        r = upload(client)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "Black hoodie"
        assert body["type"] == "top"
        assert body["warmth"] == 3
        assert body["image_path"].startswith(str(tmp_path / "images"))
        assert (tmp_path / "images").exists()

    def test_bad_extension_rejected_before_model(self, api):
        client, _ = api
        r = upload(client, filename="virus.exe")
        assert r.status_code == 422

    def test_model_down_returns_503(self, api, monkeypatch, tmp_path):
        client, app = api
        monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")

        class Down:
            def complete(self, messages, model, temperature=0.7):
                raise ConnectionError("no ollama")

        app.state.recommender._provider = lambda url: Down()
        r = upload(client)
        assert r.status_code == 503


class TestItemPhotoLifecycle:
    def test_create_claims_draft_and_delete_cleans_up(self, api, monkeypatch, tmp_path):
        client, app = api
        monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")

        from conftest import ScriptedProvider

        provider = ScriptedProvider([good_draft()])
        app.state.recommender._provider = lambda url: provider

        body = upload(client).json()
        draft_path = body["image_path"]

        # Save the item with the draft photo attached.
        r = client.post(
            "/api/items",
            json={
                "name": body["name"],
                "type": body["type"],
                "color": body["color"],
                "warmth": body["warmth"],
                "formality": body["formality"],
                "style_tags": body["style_tags"],
                "image_path": draft_path,
            },
        )
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["image_path"].endswith("1.png")  # claimed to item id
        assert not __import__("pathlib").Path(draft_path).exists()

        # Photo is served.
        pr = client.get(f"/api/items/{item['id']}/photo")
        assert pr.status_code == 200
        assert pr.content == png_bytes()

        # Deleting the item removes the photo file too.
        assert client.delete(f"/api/items/{item['id']}").status_code == 204
        assert client.get(f"/api/items/{item['id']}/photo").status_code == 404
        assert not __import__("pathlib").Path(item["image_path"]).exists()

    def test_photo_404_for_item_without_photo(self, api):
        client, _ = api
        r = client.post(
            "/api/items",
            json={"name": "Plain tee", "type": "top", "warmth": 1, "formality": 1},
        )
        item_id = r.json()["id"]
        assert client.get(f"/api/items/{item_id}/photo").status_code == 404


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
