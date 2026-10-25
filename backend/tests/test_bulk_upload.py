"""Bulk photo upload: /api/classify/bulk queues photos, classifies them
ONE AT A TIME, and reports results (a failed photo never fails the job)
plus live progress via GET /api/jobs/{id}. A photo with several garments
contributes one ok:true row PER DRAFT; a failed photo one ok:false row;
progress counts FILES, not drafts."""
import io
import json
import threading

from app.services import images


def png_bytes(size=64):
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def draft_obj(name):
    return {
        "name": name,
        "category": "hoodie",
        "type": "top",
        "color": "black",
        "warmth": 3,
        "formality": 1,
        "style_tags": "cosy",
    }


def draft_reply(name):
    return json.dumps(draft_obj(name))


def drafts_reply(names):
    """A flat-lay reply: a JSON array of draft objects."""
    objs = [draft_obj(n) for n in names]
    for obj in objs:
        if "trousers" in obj["name"].lower():
            obj.update(category="jeans", type="bottom")
    return json.dumps(objs)


def upload_bulk(client, filenames, contents=None, path="/api/classify/bulk"):
    files = [
        ("photos", (name, io.BytesIO(png_bytes() if contents is None else contents[i]), "image/png"))
        for i, name in enumerate(filenames)
    ]
    return client.post(path, files=files)


def poll(client, job_id, rounds=200):
    """Poll a job to a terminal state; return the final status payload."""
    for _ in range(rounds):
        st = client.get(f"/api/jobs/{job_id}").json()
        if st["status"] in ("done", "failed"):
            return st
    raise AssertionError(f"job {job_id} never finished: {st}")


class TestBulkClassify:
    def test_three_photos_all_ok(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([draft_reply("Shirt one"), draft_reply("Shirt two"), draft_reply("Shirt three")])
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["a.png", "b.png", "c.png"])
        assert r.status_code == 202, r.text
        st = poll(client, r.json()["job_id"])

        assert st["status"] == "done", st
        assert st["progress"] == {"done": 3, "total": 3}
        rows = st["result"]
        assert len(rows) == 3
        for i, row in enumerate(rows):
            assert row["ok"] is True
            assert row["filename"] == ["a.png", "b.png", "c.png"][i]
            assert row["draft"]["name"] == f"Shirt {['one','two','three'][i]}"
            token = row["draft"]["photo_token"]
            assert images.PHOTO_NAME_RE.match(token)
            assert images.photo_path(token).is_file()
        # Each photo got exactly one model call — the queue runs sequentially.
        assert len(provider.calls) == 3

    def test_multi_draft_photo_yields_row_per_draft(self, api):
        """File A replies with an array of 2 drafts, file B with a single
        object: 3 rows total, but progress still counts FILES and the
        provider is called once per file."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider(
            [drafts_reply(["Shirt A1", "Shirt A2"]), draft_reply("Shirt B")]
        )
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["a.png", "b.png"])
        assert r.status_code == 202, r.text
        st = poll(client, r.json()["job_id"])

        assert st["status"] == "done", st
        assert st["progress"] == {"done": 2, "total": 2}  # files, not drafts
        rows = st["result"]
        assert len(rows) == 3  # 2 from file A + 1 from file B
        assert [row["filename"] for row in rows] == ["a.png", "a.png", "b.png"]
        assert [row["draft"]["name"] for row in rows] == ["Shirt A1", "Shirt A2", "Shirt B"]
        tokens = [row["draft"]["photo_token"] for row in rows]
        assert len(set(tokens)) == 3  # a photo copy per draft
        for token in tokens:
            assert images.PHOTO_NAME_RE.match(token)
            assert images.photo_path(token).is_file()
        # One model call per FILE.
        assert len(provider.calls) == 2

    def test_mixed_failure_and_flat_lay(self, api):
        """File 0's model call fails -> ONE ok:false row; file 1 finds 2
        drafts -> 2 ok:true rows; the job still finishes done."""
        client, app = api
        from conftest import ScriptedProvider

        # ConnectionError is a network failure: ClassificationError without retry.
        provider = ScriptedProvider(
            [
                ConnectionError("no ollama"),
                drafts_reply(["Good shirt", "Good trousers"]),
            ]
        )
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["bad.png", "flat.png"])
        assert r.status_code == 202, r.text
        st = poll(client, r.json()["job_id"])

        assert st["status"] == "done", st
        assert st["progress"] == {"done": 2, "total": 2}
        rows = st["result"]
        assert len(rows) == 3  # 1 failure row + 2 draft rows
        assert rows[0]["ok"] is False
        assert rows[0]["filename"] == "bad.png"
        assert "model call failed" in rows[0]["error"]
        assert rows[0]["draft"] is None
        for row in rows[1:]:
            assert row["ok"] is True
            assert row["filename"] == "flat.png"
        assert [row["draft"]["name"] for row in rows[1:]] == ["Good shirt", "Good trousers"]
        assert len(provider.calls) == 2  # one per photo, queue continued

    def test_bad_extension_rejects_whole_request(self, api):
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([])
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["a.png", "virus.exe", "c.png"])
        assert r.status_code == 422
        # Nothing ran: no model call, no job created.
        assert provider.calls == []

    def test_empty_file_rejects_whole_request(self, api):
        client, _ = api
        r = upload_bulk(client, ["a.png", "empty.png"], contents=[png_bytes(), b""])
        assert r.status_code == 422

    def test_over_20_files_rejected(self, api):
        client, _ = api
        names = [f"n{i}.png" for i in range(21)]
        r = upload_bulk(client, names)
        assert r.status_code == 422
        assert "at most 20" in r.json()["detail"]

    def test_single_model_failure_does_not_fail_job(self, api):
        """One photo's model error -> ok:false row; the queue continues."""
        client, app = api
        from conftest import ScriptedProvider

        # ConnectionError is a network failure: ClassificationError without retry.
        provider = ScriptedProvider(
            [
                ConnectionError("no ollama"),
                draft_reply("Good shirt"),
            ]
        )
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["bad.png", "good.png"])
        assert r.status_code == 202, r.text
        st = poll(client, r.json()["job_id"])

        assert st["status"] == "done", st
        rows = st["result"]
        assert len(rows) == 2
        assert rows[0]["ok"] is False
        assert rows[0]["filename"] == "bad.png"
        assert "model call failed" in rows[0]["error"]
        assert rows[1]["ok"] is True
        assert rows[1]["draft"]["name"] == "Good shirt"
        assert len(provider.calls) == 2  # one per photo, queue continued

    def test_invalid_output_then_failure_marks_photo_failed(self, api):
        """A bad JSON reply triggers classify's one retry; both consumed
        and the photo ends ok:false while later photos still succeed."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider(
            [
                "not json at all",
                "still not json",
                draft_reply("Recovered shirt"),
            ]
        )
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["bad.png", "good.png"])
        st = poll(client, r.json()["job_id"])
        assert st["status"] == "done", st
        rows = st["result"]
        assert rows[0]["ok"] is False
        assert rows[1]["ok"] is True
        # bad.png consumed the 2 scripted attempts (initial + 1 retry).
        assert len(provider.calls) == 3

    def test_progress_visible_while_running(self, api):
        """Progress starts at {done:0,total:n} and hits done==total on the
        last poll before terminal status. Progress counts FILES."""
        client, app = api
        from conftest import ScriptedProvider

        releases = [threading.Event() for _ in range(2)]

        class Gated:
            def __init__(self):
                self.n = 0

            def complete(self, messages, model, temperature=0.7):
                releases[self.n].wait(5)
                self.n += 1
                return draft_reply(f"Shirt {self.n}")

        app.state.recommender.provider_for = lambda url: Gated()

        r = upload_bulk(client, ["a.png", "b.png"])
        job_id = r.json()["job_id"]

        st = None
        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st["status"] == "running":
                break
        assert st["status"] == "running"
        # First photo still in flight; total is known, nothing done yet.
        assert st["progress"]["total"] == 2
        releases[0].set()

        for _ in range(200):
            st = client.get(f"/api/jobs/{job_id}").json()
            if st.get("progress", {}).get("done") == 1:
                break
        assert st["progress"] == {"done": 1, "total": 2}
        releases[1].set()

        st = poll(client, job_id)
        assert st["status"] == "done"
        assert st["progress"] == {"done": 2, "total": 2}

    def test_drafts_are_served_by_existing_photo_route(self, api):
        """Bulk draft tokens reuse GET /api/classify/photo/{token}."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([draft_reply("Servable shirt")])
        app.state.recommender.provider_for = lambda url: provider

        payload = b"\x89PNG servable"
        r = upload_bulk(client, ["s.png"], contents=[payload])
        st = poll(client, r.json()["job_id"])
        token = st["result"][0]["draft"]["photo_token"]
        res = client.get(f"/api/classify/photo/{token}")
        assert res.status_code == 200
        assert res.content == payload

    def test_bulk_draft_can_be_claimed_on_item_save(self, api):
        """End to end: bulk draft -> POST /api/items with photo_token."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([draft_reply("Claimable shirt")])
        app.state.recommender.provider_for = lambda url: provider

        r = upload_bulk(client, ["k.png"])
        st = poll(client, r.json()["job_id"])
        token = st["result"][0]["draft"]["photo_token"]

        resp = client.post(
            "/api/items",
            json={
                "name": "Claimable shirt",
                "category": "t_shirt",
                "type": "top",
                "warmth": 3,
                "formality": 1,
                "photo_token": token,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["has_photo"] is True


class TestJobProgressBackwardCompat:
    def test_plain_job_reports_progress_null(self, api):
        """Jobs submitted without progress (e.g. /api/classify/async)
        still answer with progress: null — old clients see no change."""
        client, app = api
        from conftest import ScriptedProvider

        provider = ScriptedProvider([draft_reply("Solo shirt")])
        app.state.recommender.provider_for = lambda url: provider

        r = client.post(
            "/api/classify/async",
            files={"photo": ("solo.png", io.BytesIO(png_bytes()), "image/png")},
        )
        assert r.status_code == 202
        st = poll(client, r.json()["job_id"])
        assert st["status"] == "done"
        assert st["progress"] is None
        # Single-photo async results are bulk-style rows: one per draft.
        rows = st["result"]
        assert len(rows) == 1
        assert rows[0]["ok"] is True
        assert rows[0]["draft"]["name"] == "Solo shirt"
