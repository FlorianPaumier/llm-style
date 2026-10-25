"""API tests via TestClient: CRUD, validation, settings, recommend wiring."""
import io

ITEM = {
    "name": "Navy tee",
    "category": "t_shirt",
    "type": "top",
    "color": "navy",
    "warmth": 2,
    "formality": 1,
    "style_tags": "minimal",
}


class TestItemsApi:
    def test_crud_roundtrip(self, api):
        client, _ = api
        r = client.post("/api/items", json=ITEM)
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["id"] == 1
        assert created["has_photo"] is False
        assert created["photo_url"] is None
        # No filesystem path may leak in the API response.
        assert "image_path" not in created

        listing = client.get("/api/items").json()
        assert listing["items"] == [created]
        assert listing["total"] == 1 and listing["page"] == 1

        r = client.put(f"/api/items/{created['id']}", json={**ITEM, "formality": 3})
        assert r.status_code == 200 and r.json()["formality"] == 3

        assert client.delete(f"/api/items/{created['id']}").status_code == 204
        assert client.get("/api/items").json()["total"] == 0

    def test_validation_rejects_bad_type(self, api):
        client, _ = api
        r = client.post("/api/items", json={**ITEM, "type": "hat"})
        assert r.status_code == 422

    def test_404_on_missing(self, api):
        client, _ = api
        assert client.get("/api/items/42").status_code == 404
        assert client.delete("/api/items/42").status_code == 404

    def test_photo_token_must_be_server_issued(self, api):
        """Regression: image_path used to be a free string, allowing an
        arbitrary local file read via /api/items/{id}/photo."""
        client, _ = api
        for evil in ("/etc/hosts", "../../etc/hosts", "1.png/../../../etc/hosts",
                     "C:\\windows\\win.ini", "1.jpg", "draft-abc.png", "7.png"):
            r = client.post(
                "/api/items",
                json={**ITEM, "photo_token": evil},
            )
            assert r.status_code == 422, f"{evil!r} should be rejected: {r.text}"
        # Nothing was stored; the photo route serves nothing.
        item = client.post("/api/items", json=ITEM).json()
        assert client.get(f"/api/items/{item['id']}/photo").status_code == 404

    def test_update_cannot_destroy_photo_reference(self, api):
        """Regression: PUT with no photo fields used to null image_path
        and orphan the photo file."""
        client, _ = api
        from app.services import images

        # Attach a real draft photo through the token flow.
        images.images_dir().mkdir(parents=True, exist_ok=True)
        token = images.save_draft_image(b"\x89PNG fake", ".png")
        item = client.post("/api/items", json={**ITEM, "photo_token": token}).json()
        assert item["has_photo"] is True

        # A plain field edit must not drop the photo.
        r = client.put(
            f"/api/items/{item['id']}",
            json={"name": "Navy tee v2", "category": "t_shirt", "type": "top",
                  "color": "navy", "warmth": 2, "formality": 2},
        )
        assert r.status_code == 200
        assert r.json()["has_photo"] is True
        pr = client.get(f"/api/items/{item['id']}/photo")
        assert pr.status_code == 200

        # Explicit detach does remove it.
        assert client.delete(f"/api/items/{item['id']}/photo").status_code == 204
        assert client.get(f"/api/items/{item['id']}/photo").status_code == 404
        item2 = client.get(f"/api/items/{item['id']}").json()
        assert item2["has_photo"] is False


class TestItemsQuery:
    def _seed(self, client):
        for i in range(1, 16):
            client.post(
                "/api/items",
                json={"name": f"tee {i:02d}", "category": "t_shirt" if i % 2 else "jeans",
                      "type": "top" if i % 2 else "bottom",
                      "color": "navy", "warmth": (i % 5) + 1, "formality": 2},
            )

    def test_pagination(self, api):
        client, _ = api
        self._seed(client)
        body = client.get("/api/items?page=2&page_size=5").json()
        assert body["page"] == 2 and body["page_size"] == 5
        assert len(body["items"]) == 5 and body["total"] == 15 and body["pages"] == 3
        assert body["items"][0]["name"] == "tee 06"

    def test_filter_by_type(self, api):
        client, _ = api
        self._seed(client)
        body = client.get("/api/items?type=top").json()
        assert body["total"] == 8
        assert all(it["type"] == "top" for it in body["items"])

    def test_sort_desc(self, api):
        client, _ = api
        self._seed(client)
        body = client.get("/api/items?sort=name&order=desc&page_size=3").json()
        names = [it["name"] for it in body["items"]]
        assert names == ["tee 15", "tee 14", "tee 13"]

    def test_text_search(self, api):
        client, _ = api
        self._seed(client)
        # "tee 0" matches tee 01..tee 09 (names are zero-padded).
        assert client.get("/api/items?q=tee 0").json()["total"] == 9


class TestSettingsApi:
    def test_defaults_and_update(self, api):
        client, _ = api
        r = client.get("/api/settings")
        assert r.json() == {
            "city": "Paris",
            "model": "dolphin-mistral:7b",
            "ollama_url": "http://localhost:11434",
            "vision_model": "gemma3:4b",
        }
        r = client.put("/api/settings", json={"city": "Lyon"})
        assert r.json()["city"] == "Lyon"
        assert r.json()["model"] == "dolphin-mistral:7b"  # untouched fields keep defaults

    def test_absent_key_keeps_null_key_resets(self, api):
        """Regression: null used to mean 'keep current', so a setting could
        never be cleared back to its default."""
        client, _ = api
        client.put("/api/settings", json={"city": "Lyon"})
        # Absent key keeps the stored value.
        assert client.put("/api/settings", json={"model": "x:1b"}).json()["city"] == "Lyon"
        # Explicit null resets to the default.
        assert client.put("/api/settings", json={"city": None}).json()["city"] == "Paris"
        # Empty string also resets.
        client.put("/api/settings", json={"city": "Lyon"})
        assert client.put("/api/settings", json={"city": ""}).json()["city"] == "Paris"
        # Empty payload changes nothing.
        assert client.put("/api/settings", json={}).json() == client.get("/api/settings").json()


class TestRecommendApi:
    def test_empty_wardrobe_returns_gaps_not_500(self, api):
        client, app = api

        class FailingWeather:
            def current(self, city):
                from app.services.weather import WeatherUnavailable

                raise WeatherUnavailable("no net")

        app.state.weather = FailingWeather()
        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "chill", "occasion": "casual"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["outfit"] == []
        assert body["gaps"]
        assert body["history_id"] is not None  # even misses are logged

    def test_full_flow_with_fallback_stylist(self, api):
        client, app = api
        from tests.conftest import full_wardrobe, FakeWeatherService

        for it in full_wardrobe():
            client.post(
                "/api/items",
                json={
                    "name": it["name"],
                    "category": it["category"],
                    "type": it["type"],
                    "color": it["color"],
                    "warmth": it["warmth"],
                    "formality": it["formality"],
                    "style_tags": it["style_tags"],
                },
            )
        app.state.weather = FakeWeatherService(temp_c=18.0)

        # Break Ollama so the deterministic fallback kicks in.
        class DownProvider:
            def complete(self, messages, model):
                raise ConnectionError("ollama down")

        app.state.recommender.provider_for = lambda url: DownProvider()

        r = client.post(
            "/api/outfits/recommend",
            json={"mood": "feeling cosy and chill", "occasion": "casual"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["source"] == "fallback"
        assert len(body["outfit"]) >= 3
        assert {o["slot"] for o in body["outfit"]} >= {"top", "bottom", "shoes"}

    def test_recommend_async_job(self, api):
        client, app = api
        from tests.conftest import full_wardrobe, FakeWeatherService, ScriptedProvider
        from app.services.candidates import select
        from app.services import stylist
        import json as _json
        import datetime

        for it in full_wardrobe():
            client.post("/api/items", json={
                "name": it["name"], "category": it["category"],
                "type": it["type"], "color": it["color"],
                "warmth": it["warmth"], "formality": it["formality"],
                "style_tags": it["style_tags"],
            })
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        cs = select(full_wardrobe(), 18.0, "casual", seed)
        reply = _json.dumps({
            "title": "Async pick",
            "item_ids": {
                "top": cs.slots["top"][0]["id"],
                "bottom": cs.slots["bottom"][0]["id"],
                "shoes": cs.slots["shoes"][0]["id"],
                "outerwear": None,
                "accessories": [],
            },
            "rationale": "Fresh async fit.",
        })
        provider = ScriptedProvider([reply])
        app.state.recommender.provider_for = lambda url: provider

        r = client.post("/api/outfits/recommend/async", json={"mood": "chill"})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]

        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st["status"] in ("done", "failed"):
                break
        assert st["status"] == "done", st
        assert st["result"]["title"] == "Async pick"
        assert st["result"]["source"] == "llm"

        # Unknown job id -> 404.
        assert client.get("/api/jobs/nope").status_code == 404


class TestHistoryApi:
    def test_history_and_mark_worn(self, api):
        client, app = api
        from tests.conftest import full_wardrobe, FakeWeatherService, ScriptedProvider
        from app.services.candidates import select
        import json as _json
        import datetime

        for it in full_wardrobe():
            client.post("/api/items", json={
                "name": it["name"], "category": it["category"],
                "type": it["type"], "color": it["color"],
                "warmth": it["warmth"], "formality": it["formality"],
            })
        app.state.weather = FakeWeatherService(temp_c=18.0)
        seed = int(datetime.datetime.now().strftime("%Y%m%d"))
        cs = select(full_wardrobe(), 18.0, "casual", seed)
        reply = _json.dumps({
            "title": "Worn test",
            "item_ids": {
                "top": cs.slots["top"][0]["id"],
                "bottom": cs.slots["bottom"][0]["id"],
                "shoes": cs.slots["shoes"][0]["id"],
                "outerwear": None,
                "accessories": [],
            },
            "rationale": "x",
        })
        app.state.recommender.provider_for = lambda url: ScriptedProvider([reply])

        rec = client.post("/api/outfits/recommend", json={"mood": "chill"}).json()
        worn_ids = [o["item"]["id"] for o in rec["outfit"]]

        hist = client.get("/api/history").json()
        assert len(hist) == 1
        assert hist[0]["id"] == rec["history_id"]
        assert [i["id"] for i in hist[0]["items"]] == worn_ids
        assert hist[0]["worn_at"] is None

        # Mark worn: increments times_worn once, idempotent afterwards.
        r = client.post(f"/api/history/{rec['history_id']}/worn").json()
        assert r["already_worn"] is False
        r2 = client.post(f"/api/history/{rec['history_id']}/worn").json()
        assert r2["already_worn"] is True

        detail = client.get(f"/api/history/{rec['history_id']}").json()
        assert detail["worn_at"] is not None
        for item_id in worn_ids:
            it = client.get(f"/api/items/{item_id}").json()
            assert it["times_worn"] == 1

    def test_mark_worn_404(self, api):
        client, _ = api
        assert client.post("/api/history/999/worn").status_code == 404


class TestAppMeta:
    def test_health(self, api):
        client, _ = api
        assert client.get("/api/health").json()["status"] == "ok"

    def test_app_download_shape(self, api):
        client, _ = api
        dl = client.get("/api/app/download").json()
        assert dl["primary_url"].startswith("http")
        assert dl["manifest_url"] == "/manifest.webmanifest"
        assert "Add to Home Screen" in dl["install_hint"]

    def test_qr_svg(self, api):
        client, _ = api
        r = client.get("/api/app/qr.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.content.startswith(b"<svg")

    def test_cors_allowed(self, api):
        client, _ = api
        pre = client.options(
            "/api/items",
            headers={
                "Origin": "http://phone.local",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert pre.status_code == 200
        assert pre.headers["access-control-allow-origin"] == "*"
        get = client.get("/api/items", headers={"Origin": "http://phone.local"})
        assert get.headers["access-control-allow-origin"] == "*"
