"""FastAPI application factory and API routes."""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import repo
from .config import PROJECT_ROOT, AppConfig, load_config
from .db import connect, init_db
from .models import (
    Item,
    ItemIn,
    RecommendRequest,
    RecommendResponse,
    Settings,
    SettingsIn,
    Weather,
)
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
        return repo.items.create(conn, payload)

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
        if not repo.items.delete(conn, item_id):
            raise HTTPException(404, f"Item {item_id} not found")

    # --- Settings & weather (phase 3) and recommendation (phase 6) ----
    register_settings_routes(app, get_conn)
    register_weather_routes(app, get_conn)
    register_recommend_routes(app, get_conn)

    # --- Static frontend ----------------------------------------------
    static_dir = PROJECT_ROOT / "frontend"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


def register_settings_routes(app: FastAPI, get_conn) -> None:
    from . import repo as repo_mod

    @app.get("/api/settings", response_model=Settings)
    def get_settings(conn=Depends(get_conn)):
        row = repo_mod.settings.get(conn)
        cfg = app.state.config
        return Settings(
            city=row["city"] or cfg.default_city,
            model=row["model"] or cfg.default_model,
            ollama_url=row["ollama_url"] or cfg.default_ollama_url,
        )

    @app.put("/api/settings", response_model=Settings)
    def update_settings(payload: SettingsIn, conn=Depends(get_conn)):
        # Merge: only fields the client sent change; blanks fall back to defaults.
        row = repo_mod.settings.get(conn)
        cfg = app.state.config
        city = payload.city or row["city"] or cfg.default_city
        model = payload.model or row["model"] or cfg.default_model
        ollama_url = payload.ollama_url or row["ollama_url"] or cfg.default_ollama_url
        repo_mod.settings.update(conn, city, model, ollama_url)
        return Settings(city=city, model=model, ollama_url=ollama_url)


def register_weather_routes(app: FastAPI, get_conn) -> None:

    @app.get("/api/weather", response_model=Weather)
    def get_weather(conn=Depends(get_conn)):
        row = repo.settings.get(conn)
        city = row["city"] or app.state.config.default_city
        try:
            return app.state.weather.current(city)
        except Exception:
            raise HTTPException(503, f"Live weather unavailable for {city!r}")


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
