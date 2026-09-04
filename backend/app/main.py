"""FastAPI application factory and API routes."""
from __future__ import annotations

import base64
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import repo
from .config import PROJECT_ROOT, AppConfig, load_config
from .db import connect, init_db
from .llm.provider import OllamaProvider
from .models import (
    DraftItemResponse,
    Item,
    ItemIn,
    RecommendRequest,
    RecommendResponse,
    Settings,
    SettingsIn,
    Weather,
)
from .services import classify, images
from .services.recommend import RecommendationService
from .services.weather import WeatherService


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    init_db(config.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.weather = WeatherService()
        app.state.recommender = RecommendationService()
        images.sweep_stale_drafts()  # drop photos abandoned by unsaved drafts
        yield

    app = FastAPI(title="llm-style", lifespan=lifespan)

    def get_conn() -> sqlite3.Connection:
        # A fresh connection per request; SQLite handles this fine locally.
        conn = connect(config.db_path)
        try:
            yield conn
        finally:
            conn.close()

    # --- Wardrobe CRUD -------------------------------------------------

    @app.get("/api/items", response_model=list[Item])
    def list_items(conn=Depends(get_conn)):
        return repo.items.list_all(conn)

    @app.post("/api/items", response_model=Item, status_code=201)
    def create_item(payload: ItemIn, conn=Depends(get_conn)):
        row = repo.items.create(conn, payload)
        # A photo uploaded during classify sits under a draft-* name; rename
        # it to the item's id so its lifetime is tied to the item.
        if payload.image_path:
            final = images.claim_image(payload.image_path, row["id"])
            if final:
                repo.items.update_image_path(conn, row["id"], final)
                row = repo.items.get(conn, row["id"])
        return row

    @app.get("/api/items/{item_id}", response_model=Item)
    def get_item(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        return row

    @app.put("/api/items/{item_id}", response_model=Item)
    def update_item(item_id: int, payload: ItemIn, conn=Depends(get_conn)):
        row = repo.items.update(conn, item_id, payload)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        return row

    @app.delete("/api/items/{item_id}", status_code=204)
    def delete_item(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        repo.items.delete(conn, item_id)
        images.delete_image(row["image_path"])

    # --- Settings & weather, recommendation, and photo classification ----
    register_settings_routes(app, get_conn)
    register_weather_routes(app, get_conn)
    register_recommend_routes(app, get_conn)
    register_classify_routes(app, get_conn)

    # --- Static frontend ----------------------------------------------
    static_dir = PROJECT_ROOT / "frontend"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def register_settings_routes(app: FastAPI, get_conn) -> None:
    from . import repo as repo_mod

    def current_settings(conn) -> Settings:
        row = repo_mod.settings.get(conn)
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
        # Merge: only fields the client sent change; blanks fall back to defaults.
        row = repo_mod.settings.get(conn)
        cfg = app.state.config
        city = payload.city or row["city"] or cfg.default_city
        model = payload.model or row["model"] or cfg.default_model
        ollama_url = payload.ollama_url or row["ollama_url"] or cfg.default_ollama_url
        vision_model = payload.vision_model or row["vision_model"] or cfg.default_vision_model
        repo_mod.settings.update(conn, city, model, ollama_url, vision_model)
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
    """Photo upload -> vision-model draft; draft photos are claimed on save."""

    @app.post("/api/classify", response_model=DraftItemResponse)
    def classify_photo(photo: UploadFile = File(...), conn=Depends(get_conn)):
        ext = images.validate_extension(photo.filename or "")
        if not ext:
            raise HTTPException(422, "Photo must be .jpg, .jpeg, .png or .webp")

        data = photo.file.read()
        if not data:
            raise HTTPException(422, "Empty upload")
        if len(data) > images.MAX_IMAGE_BYTES:
            raise HTTPException(413, "Photo must be under 10 MB")

        row = repo.settings.get(conn)
        cfg = app.state.config
        ollama_url = row["ollama_url"] or cfg.default_ollama_url
        vision_model = row["vision_model"] or cfg.default_vision_model

        provider = app.state.recommender._provider(ollama_url)
        try:
            draft = classify.classify(
                provider,
                vision_model,
                base64.b64encode(data).decode("ascii"),
            )
        except classify.ClassificationError as exc:
            raise HTTPException(503, f"Vision model unavailable: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(503, f"Vision model returned unusable output: {exc}") from exc

        # Keep the photo so the user sees it while reviewing the draft form.
        saved = images.save_draft_image(data, ext)
        return DraftItemResponse(
            name=draft.name,
            type=draft.type,
            color=draft.color,
            warmth=draft.warmth,
            formality=draft.formality,
            style_tags=draft.style_tags,
            image_path=str(saved),
        )

    @app.get("/api/items/{item_id}/photo")
    def get_item_photo(item_id: int, conn=Depends(get_conn)):
        row = repo.items.get(conn, item_id)
        if row is None:
            raise HTTPException(404, f"Item {item_id} not found")
        if not row["image_path"]:
            raise HTTPException(404, "This item has no photo")
        path = Path(row["image_path"])
        if not path.is_file():
            raise HTTPException(404, "Photo file missing")
        media_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
        }.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media_type)


def register_recommend_routes(app: FastAPI, get_conn) -> None:

    @app.post("/api/outfits/recommend", response_model=RecommendResponse)
    def recommend(payload: RecommendRequest, conn=Depends(get_conn)):
        settings_row = repo.settings.get(conn)
        cfg = app.state.config
        return app.state.recommender.recommend(
            conn=conn,
            config=cfg,
            city=settings_row["city"] or cfg.default_city,
            model=settings_row["model"] or cfg.default_model,
            ollama_url=settings_row["ollama_url"] or cfg.default_ollama_url,
            weather_service=app.state.weather,
            mood=payload.mood,
            occasion=payload.occasion,
            weather_override_c=payload.weather_override_c,
        )


app = create_app()
