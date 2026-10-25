"""FastAPI application factory and API routes.

API surface (mobile-ready):
- /api/items            GET (page/type/warmth/formality/q/sort/order), POST
- /api/items/{id}       GET, PUT (photo-preserving), DELETE
- /api/items/{id}/photo GET, POST (photo_token), DELETE
- /api/personas        GET, POST (name, optional description)
- /api/personas/{id}   PUT (absent key = keep; null/"" description clears)
- /api/settings         GET, PUT (absent key = keep, null = reset to default)
- /api/weather          GET
- /api/outfits/recommend        POST (sync, desktop use)
- /api/outfits/recommend/async  POST -> {job_id}; poll /api/jobs/{id}
- /api/classify         POST (sync); /api/classify/async POST -> {job_id}
- /api/jobs/{id}        GET
- /api/history          GET; /api/history/{id}/worn POST
- /api/app/download     GET — install info for phones (URLs + QR)
"""
from __future__ import annotations

import base64
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import repo
from .api_quickadd import register_quickadd_routes
from .config import PROJECT_ROOT, AppConfig, load_config
from .db import connect, init_db
from .llm.provider import OllamaProvider
from .models import (
    AppDownload,
    BulkClassifyResultItem,
    ClassifyResponse,
    DraftItemResponse,
    Item,
    ItemIn,
    ItemSortKey,
    ItemUpdate,
    ItemListResponse,
    JobCreated,
    JobStatus,
    MarkWornResponse,
    OutfitHistoryEntry,
    Persona,
    PersonaIn,
    PersonaUpdate,
    PhotoIn,
    RecommendRequest,
    RecommendResponse,
    Settings,
    SettingsIn,
    Weather,
)
from .services import classify, images, network
from .services.jobs import JobStore
from .services.recommend import RecommendationService
from .services.weather import WeatherService

_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
}


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    init_db(config.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.weather = WeatherService()
        app.state.recommender = RecommendationService()
        app.state.jobs = JobStore()
        images.sweep_stale_drafts()  # drop photos abandoned by unsaved drafts
        yield
        app.state.jobs.shutdown()

    app = FastAPI(title="llm-style", lifespan=lifespan)

    # Same-origin desktop use needs no CORS; a phone's webview or a hosted
    # mobile client does. Allowlist configurable via LLM_STYLE_CORS_ORIGINS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_conn() -> sqlite3.Connection:
        # A fresh connection per request; SQLite handles this fine locally.
        conn = connect(config.db_path)
        try:
            yield conn
        finally:
            conn.close()

    # --- Wardrobe CRUD -------------------------------------------------

    @app.get("/api/items", response_model=ItemListResponse)
    def list_items(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        persona_id: int | None = Query(None, ge=1),
        type: str | None = Query(None, pattern="^(top|bottom|shoes|outerwear|accessory)$"),
        warmth: int | None = Query(None, ge=1, le=5),
        formality: int | None = Query(None, ge=1, le=5),
        q: str | None = Query(None, max_length=100),
        sort: ItemSortKey | None = None,
        order: str = Query("asc", pattern="^(asc|desc)$"),
        conn=Depends(get_conn),
    ):
        # Absent persona_id = the default (first) persona, so existing
        # clients see exactly what they always saw.
        pid = persona_id
        if pid is None:
            pid = repo.personas.first(conn)["id"]
        rows, total = repo.items.query(
            conn, persona_id=pid, type=type, warmth=warmth, formality=formality, q=q,
            sort=sort, order=order,
            limit=page_size, offset=(page - 1) * page_size,
        )
        pages = max(1, -(-total // page_size))
        return ItemListResponse(
            items=[repo.items.to_item(r) for r in rows],
            total=total, page=page, page_size=page_size, pages=pages,
        )

    @app.post("/api/items", response_model=Item, status_code=201)
    def create_item(payload: ItemIn, conn=Depends(get_conn)):
        # Only a valid draft token issued by /api/classify is accepted;
        # paths, traversal or foreign names are rejected outright.
        if payload.photo_token is not None and not images.draft_exists(payload.photo_token):
            raise HTTPException(422, "Unknown photo token — re-upload the photo first")
        persona = repo.personas.get(conn, payload.persona_id) if payload.persona_id else None
        if payload.persona_id and persona is None:
            raise HTTPException(422, f"Unknown persona id {payload.persona_id}")
        row = repo.items.create(conn, payload, persona_id=persona["id"] if persona else None)
        if payload.photo_token is not None:
            final = images.claim_image(payload.photo_token, row["id"])
            if final:
                repo.items.update_image_path(conn, row["id"], final)
                row = repo.items.get(conn, row["id"])
        return repo.items.to_item(row)

    @app.get("/api/items/{item_id}", response_model=Item)
    def get_item(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        return repo.items.to_item(row)

    @app.put("/api/items/{item_id}", response_model=Item)
    def update_item(item_id: int, payload: ItemUpdate, conn=Depends(get_conn)):
        # Full field update; the photo is intentionally untouched here —
        # an edit can never orphan the photo file (use the photo endpoints).
        # persona_id moves the item to another wardrobe when sent.
        if payload.persona_id is not None and repo.personas.get(conn, payload.persona_id) is None:
            raise HTTPException(422, f"Unknown persona id {payload.persona_id}")
        row = repo.items.update(conn, item_id, payload)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        return repo.items.to_item(row)

    @app.delete("/api/items/{item_id}", status_code=204)
    def delete_item(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        repo.items.delete(conn, item_id)
        images.delete_image(row["image_path"])

    # --- Item photos (tokens in, files out — never filesystem paths) ---

    @app.get("/api/items/{item_id}/photo")
    def get_item_photo(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        path = images.photo_path(row["image_path"]) if row["image_path"] else None
        if path is None or not path.is_file():
            raise HTTPException(404, "This item has no photo")
        media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type)

    @app.post("/api/items/{item_id}/photo", response_model=Item, status_code=201)
    def attach_photo(item_id: int, payload: PhotoIn, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        if not images.draft_exists(payload.photo_token):
            raise HTTPException(422, "Unknown photo token — re-upload the photo first")
        final = images.claim_image(payload.photo_token, item_id)
        if final is None:
            raise HTTPException(422, "Photo could not be attached")
        # Replace any previous photo file, then point the item at the new
        # one. Skip when the claim already overwrote the same-named file.
        if row["image_path"] and row["image_path"] != final:
            images.delete_image(row["image_path"])
        repo.items.update_image_path(conn, item_id, final)
        return repo.items.to_item(repo.items.get(conn, item_id))

    @app.delete("/api/items/{item_id}/photo", status_code=204)
    def detach_photo(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        if not row["image_path"]:
            raise HTTPException(404, "This item has no photo")
        repo.items.update_image_path(conn, item_id, None)
        images.delete_image(row["image_path"])

    # --- Settings, weather, recommendations ----------------------------

    register_persona_routes(app, get_conn)
    register_settings_routes(app, get_conn)
    register_weather_routes(app, get_conn)
    register_recommend_routes(app, get_conn)
    register_classify_routes(app, get_conn)
    register_quickadd_routes(app, get_conn)
    register_history_routes(app, get_conn)
    register_app_routes(app)

    # --- Static frontend & PWA ------------------------------------------
    static_dir = PROJECT_ROOT / "frontend"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def register_persona_routes(app: FastAPI, get_conn) -> None:
    """The people whose wardrobes the app dresses (multi-persona)."""

    @app.get("/api/personas", response_model=list[Persona])
    def list_personas(conn=Depends(get_conn)):
        return repo.personas.list_all(conn)

    @app.post("/api/personas", response_model=Persona, status_code=201)
    def create_persona(payload: PersonaIn, conn=Depends(get_conn)):
        return repo.personas.create(
            conn, payload.name.strip(), payload.description, payload.gender
        )

    @app.put("/api/personas/{persona_id}", response_model=Persona)
    def update_persona(persona_id: int, payload: PersonaUpdate, conn=Depends(get_conn)):
        """Merge semantics like /api/settings: a key absent from the payload
        keeps its current value; a key explicitly sent sets it — for
        description, null or "" clears it; for gender, null resets to
        unspecified."""
        row = repo.personas.get(conn, persona_id)
        if row is None:
            raise HTTPException(404, f"Persona {persona_id} not found")
        sent = payload.model_fields_set  # distinguishes absent from null

        if "name" in sent and payload.name is not None:
            repo.personas.update(conn, persona_id, name=payload.name.strip())
        if "description" in sent:
            repo.personas.update_description(
                conn, persona_id, payload.description
            )
        if "gender" in sent:
            repo.personas.update(conn, persona_id, gender=payload.gender or "unspecified")
        return repo.personas.get(conn, persona_id)

    @app.delete("/api/personas/{persona_id}", status_code=204)
    def delete_persona(persona_id: int, conn=Depends(get_conn)):
        if repo.personas.get(conn, persona_id) is None:
            raise HTTPException(404, f"Persona {persona_id} not found")
        if repo.personas.count(conn) <= 1:
            raise HTTPException(400, "Can't delete the last persona")
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM items WHERE persona_id = ?", (persona_id,)
        ).fetchone()["n"]
        if remaining:
            raise HTTPException(
                409,
                f"Persona still has {remaining} item(s) — move or delete them first",
            )
        repo.personas.delete(conn, persona_id)


def register_settings_routes(app: FastAPI, get_conn) -> None:
    def current_settings(conn) -> Settings:
        row = repo.settings.get(conn)
        cfg = app.state.config
        return Settings(
            city=row["city"] or cfg.default_city,
            model=row["model"] or cfg.default_model,
            ollama_url=row["ollama_url"] or cfg.default_ollama_url,
            vision_model=row["vision_model"] or cfg.default_vision_model,
        )

    @app.get("/api/settings", response_model=Settings)
    def get_settings(conn=Depends(get_conn)):
        return current_settings(conn)

    @app.put("/api/settings", response_model=Settings)
    def update_settings(payload: SettingsIn, conn=Depends(get_conn)):
        """Merge semantics: a key absent from the payload keeps its current
        value; a key explicitly sent (including null/empty) sets it — null
        or "" resets to the default.
        """
        row = repo.settings.get(conn)
        cfg = app.state.config
        sent = payload.model_fields_set  # distinguishes absent from null

        def merged(field: str, incoming: str | None, current: str | None, default: str) -> str:
            if field not in sent:
                return current or default
            if incoming is None or not incoming.strip():
                return default
            return incoming.strip()

        city = merged("city", payload.city, row["city"], cfg.default_city)
        model = merged("model", payload.model, row["model"], cfg.default_model)
        ollama_url = merged(
            "ollama_url", payload.ollama_url, row["ollama_url"], cfg.default_ollama_url
        )
        vision_model = merged(
            "vision_model", payload.vision_model, row["vision_model"], cfg.default_vision_model
        )
        repo.settings.update(conn, city, model, ollama_url, vision_model)
        return current_settings(conn)


def register_weather_routes(app: FastAPI, get_conn) -> None:

    @app.get("/api/weather", response_model=Weather)
    def get_weather(conn=Depends(get_conn)):
        row = repo.settings.get(conn)
        city = row["city"] or app.state.config.default_city
        try:
            return app.state.weather.current(city)
        except Exception:
            raise HTTPException(503, f"Live weather unavailable for {city!r}")


def register_classify_routes(app: FastAPI, get_conn) -> None:
    """Photo upload -> vision-model drafts (possibly several per photo, e.g.
    a flat-lay); draft photos are claimed on save, one token per draft."""

    def classify_draft(photo_bytes: bytes, ext: str) -> ClassifyResponse:
        """One photo -> its drafts (ONE model call + one draft photo on disk
        PER DRAFT, so each is independently claimable on item save).

        Shared by the single-photo routes and the bulk queue; raises
        HTTPException(503) when the vision model fails.
        """
        job_conn = connect(app.state.config.db_path)
        try:
            row = repo.settings.get(job_conn)
            cfg = app.state.config
            ollama_url = row["ollama_url"] or cfg.default_ollama_url
            vision_model = row["vision_model"] or cfg.default_vision_model

            provider = app.state.recommender.provider_for(ollama_url)
            try:
                drafts = classify.classify_multi(
                    provider,
                    vision_model,
                    base64.b64encode(photo_bytes).decode("ascii"),
                )
            except classify.ClassificationError as exc:
                raise HTTPException(503, f"Vision model unavailable: {exc}") from exc
            except ValueError as exc:
                raise HTTPException(503, f"Vision model returned unusable output: {exc}") from exc

            # Keep the photo once per draft so each review form (and each
            # later save) can claim its own copy of the bytes.
            items = [
                DraftItemResponse(
                    name=draft.name,
                    category=draft.category,
                    type=draft.type,
                    color=draft.color,
                    warmth=draft.warmth,
                    formality=draft.formality,
                    style_tags=draft.style_tags,
                    photo_token=images.save_draft_image(photo_bytes, ext),
                )
                for draft in drafts
            ]
            return ClassifyResponse(items=items)
        finally:
            job_conn.close()

    def run_classify(photo_bytes: bytes, ext: str) -> ClassifyResponse:
        # Own connection: this runs in a job/thread long after the
        # submitting request (and its connection) is gone.
        return classify_draft(photo_bytes, ext)

    def draft_rows(photo_bytes: bytes, ext: str, filename: str) -> list[BulkClassifyResultItem]:
        """One photo -> one ok:true row PER DRAFT (a flat-lay with k items
        yields k rows sharing the filename, each with its own draft+token)."""
        return [
            BulkClassifyResultItem(ok=True, filename=filename, draft=draft)
            for draft in run_classify(photo_bytes, ext).items
        ]

    async def read_upload(photo: UploadFile) -> tuple[bytes, str]:
        ext = images.validate_extension(photo.filename or "")
        if not ext:
            raise HTTPException(422, "Photo must be .jpg, .jpeg, .png or .webp")
        data = await photo.read()
        if not data:
            raise HTTPException(422, "Empty upload")
        if len(data) > images.MAX_IMAGE_BYTES:
            raise HTTPException(413, "Photo must be under 10 MB")
        return data, ext

    MAX_BULK_PHOTOS = 20

    @app.post("/api/classify", response_model=ClassifyResponse)
    async def classify_photo(photo: UploadFile = File(...)):
        data, ext = await read_upload(photo)
        # The vision call blocks for tens of seconds — keep it off the
        # event loop so job polling and other requests stay responsive.
        return await run_in_threadpool(run_classify, data, ext)

    @app.post("/api/classify/async", response_model=JobCreated, status_code=202)
    async def classify_photo_async(photo: UploadFile = File(...)):
        data, ext = await read_upload(photo)
        filename = photo.filename or ""

        # The job result must fit JobStatus.result's union, which predates
        # ClassifyResponse — so a single async photo is reported like a
        # one-file bulk job: one ok:true row per draft found in the photo.
        # Clients polling /api/jobs/{id} get the same per-draft rows the
        # bulk queue produces, grouped by filename.
        def work():
            try:
                return [r.model_dump() for r in draft_rows(data, ext, filename)]
            except HTTPException as exc:
                raise RuntimeError(
                    str(exc.detail) if exc.detail is not None else str(exc)
                ) from exc

        job_id = app.state.jobs.submit(work)
        return JobCreated(job_id=job_id, status_url=f"/api/jobs/{job_id}")

    @app.post("/api/classify/bulk", response_model=JobCreated, status_code=202)
    async def classify_photos_bulk(photos: list[UploadFile] = File(...)):
        """Queue MULTIPLE photos; classify them one at a time.

        Ten photos must not fire ten simultaneous 30s vision calls —
        Ollama handles one request reliably — so one job walks the list
        sequentially. A photo that fails never fails the job: it becomes
        an {ok: false, error} row while the queue continues. A photo with
        several garments (flat-lay) contributes one ok:true row PER DRAFT.
        """
        if len(photos) > MAX_BULK_PHOTOS:
            raise HTTPException(
                422, f"Too many photos: {len(photos)} sent, at most {MAX_BULK_PHOTOS} per request"
            )
        uploads = [await read_upload(p) for p in photos]  # all-or-nothing
        filenames = [p.filename or "" for p in photos]

        def work(report):
            results: list[BulkClassifyResultItem] = []
            report({"done": 0, "total": len(uploads)})  # queue size is known up front
            files_done = 0
            for filename, (data, ext) in zip(filenames, uploads):
                try:
                    # One model call per photo; k drafts -> k rows.
                    results.extend(draft_rows(data, ext, filename))
                except HTTPException as exc:  # model down / bad output for THIS photo
                    results.append(
                        BulkClassifyResultItem(
                            ok=False,
                            filename=filename,
                            error=str(exc.detail) if exc.detail is not None else str(exc),
                        )
                    )
                files_done += 1
                report({"done": files_done, "total": len(uploads)})
            return [item.model_dump() for item in results]

        job_id = app.state.jobs.submit_reporting(work)
        return JobCreated(job_id=job_id, status_url=f"/api/jobs/{job_id}")

    @app.get("/api/classify/photo/{token}")
    def draft_photo(token: str):
        """Serve a draft photo so the user can see it while reviewing the
        form. Only live draft tokens resolve — no arbitrary file reads."""
        path = images.photo_path(token)
        if path is None or not token.startswith("draft-") or not path.is_file():
            raise HTTPException(404, "No such draft photo")
        media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type)


def register_recommend_routes(app: FastAPI, get_conn) -> None:
    def settings_row(conn):
        row = repo.settings.get(conn)
        cfg = app.state.config
        return {
            "city": row["city"] or cfg.default_city,
            "model": row["model"] or cfg.default_model,
            "ollama_url": row["ollama_url"] or cfg.default_ollama_url,
        }

    def check_persona_ids(conn, persona_ids: list[int] | None) -> None:
        if persona_ids:
            for pid in persona_ids:
                if repo.personas.get(conn, pid) is None:
                    raise HTTPException(422, f"Unknown persona id {pid}")

    @app.post("/api/outfits/recommend", response_model=RecommendResponse)
    async def recommend(payload: RecommendRequest, conn=Depends(get_conn)):
        s = settings_row(conn)
        check_persona_ids(conn, payload.persona_ids)
        # The LLM call can take tens of seconds; run it off the event loop.
        return await run_in_threadpool(
            app.state.recommender.recommend,
            conn=conn,
            config=app.state.config,
            city=s["city"],
            model=s["model"],
            ollama_url=s["ollama_url"],
            weather_service=app.state.weather,
            mood=payload.mood,
            occasion=payload.occasion,
            activity=payload.activity,
            weather_override_c=payload.weather_override_c,
            persona_ids=payload.persona_ids,
            count=payload.count,
        )

    @app.post("/api/outfits/recommend/async", response_model=JobCreated, status_code=202)
    def recommend_async(payload: RecommendRequest, conn=Depends(get_conn)):
        """Submit a recommendation to the background queue; poll /api/jobs/{id}.

        Each job gets its own DB connection so the request's connection can
        close while the model thinks.
        """
        s = settings_row(conn)
        check_persona_ids(conn, payload.persona_ids)

        def work():
            job_conn = connect(app.state.config.db_path)
            try:
                return app.state.recommender.recommend(
                    conn=job_conn,
                    config=app.state.config,
                    city=s["city"],
                    model=s["model"],
                    ollama_url=s["ollama_url"],
                    weather_service=app.state.weather,
                    mood=payload.mood,
                    occasion=payload.occasion,
                    activity=payload.activity,
                    weather_override_c=payload.weather_override_c,
                    persona_ids=payload.persona_ids,
                    count=payload.count,
                )
            finally:
                job_conn.close()

        job_id = app.state.jobs.submit(work)
        return JobCreated(job_id=job_id, status_url=f"/api/jobs/{job_id}")

    @app.get("/api/jobs/{job_id}", response_model=JobStatus)
    def job_status(job_id: str):
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"Job {job_id} not found (unknown or expired)")
        return JobStatus(**job)


def register_history_routes(app: FastAPI, get_conn) -> None:

    @app.get("/api/history", response_model=list[OutfitHistoryEntry])
    def get_history(
        limit: int = Query(20, ge=1, le=100),
        persona_id: int | None = Query(None, ge=1),
        conn=Depends(get_conn),
    ):
        entries = []
        for row in repo.history.recent(conn, limit, persona_id=persona_id):
            entries.append(_history_entry(conn, row))
        return entries

    @app.get("/api/history/{history_id}", response_model=OutfitHistoryEntry)
    def get_history_entry(history_id: int, conn=Depends(get_conn)):
        row = repo.history.get(conn, history_id)
        if row is None:
            raise HTTPException(404, f"History entry {history_id} not found")
        return _history_entry(conn, row)

    @app.post("/api/history/{history_id}/worn", response_model=MarkWornResponse)
    def mark_worn(history_id: int, conn=Depends(get_conn)):
        row = repo.history.get(conn, history_id)
        if row is None:
            raise HTTPException(404, f"History entry {history_id} not found")
        already = bool(row["worn_at"])
        if not already:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            repo.history.mark_worn(conn, history_id, now)
            repo.items.increment_worn(conn, json.loads(row["item_ids_json"]))
        return MarkWornResponse(
            history_id=history_id,
            already_worn=already,
            item_ids=json.loads(row["item_ids_json"]),
        )

    def _history_entry(conn, row: dict) -> OutfitHistoryEntry:
        weather = None
        if row["weather_json"]:
            try:
                weather = Weather.model_validate_json(row["weather_json"])
            except Exception:
                weather = None
        item_ids = json.loads(row["item_ids_json"])
        items = [repo.items.to_item(r) for r in repo.items.get_many(conn, item_ids)]
        return OutfitHistoryEntry(
            id=row["id"],
            created_at=row["created_at"],
            mood=row["mood"],
            occasion=row["occasion"],
            weather=weather,
            items=items,
            rationale=row["rationale"],
            source=row["source"],
            worn_at=row["worn_at"],
            persona_id=row.get("persona_id"),
        )


def register_app_routes(app: FastAPI) -> None:
    """Easy phone download: one endpoint tells clients where to point."""

    def _download_info(request: Request) -> AppDownload:
        # Phones on the same Wi-Fi reach the app over the LAN address; the
        # loopback URL only works on the machine running the server.
        base = request.base_url
        scheme = "https" if base.scheme == "https" else "http"
        port = base.port or (443 if scheme == "https" else 80)
        hosts = network.lan_addresses()
        if hosts:
            # The QR encodes the LAN URL: it is scanned by a phone, and the
            # page is usually requested from the desktop (whose own base URL
            # would be an unusable localhost link).
            primary = f"{scheme}://{hosts[0]}:{port}"
        elif network.is_own_address(urlparse(str(base)).hostname or ""):
            primary = str(base).rstrip("/")
        else:
            primary = str(base).rstrip("/")
        return AppDownload(
            primary_url=primary,
            lan_urls=[f"{scheme}://{host}:{port}" for host in hosts],
            qr_svg_url="/api/app/qr.svg",
            manifest_url="/manifest.webmanifest",
            install_hint=(
                "Open this page on your phone, then use your browser's "
                "'Add to Home Screen' / 'Install app' to download it."
            ),
        )

    @app.get("/api/app/download", response_model=AppDownload)
    def app_download(request: Request):
        return _download_info(request)

    @app.get("/api/app/qr.svg")
    def app_qr(request: Request):
        """QR encoding the app URL — scan with a phone camera to load it."""
        svg = network.qr_svg(_download_info(request).primary_url)
        return Response(svg, media_type="image/svg+xml")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "1.0"}


app = create_app()
