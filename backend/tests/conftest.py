"""Shared test fixtures: temp DB, wardrobe factory, fake providers.

Hermetic: env vars are pointed at a temp dir BEFORE app.main is imported,
so the module-level `app = create_app()` and the images dir never touch
the real data/ directory (no user DB, no user photos).
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

# Must run before app.main / app.config / app.services.images are imported.
_TMP = Path(tempfile.mkdtemp(prefix="llm-style-tests-"))
os.environ["LLM_STYLE_DB"] = str(_TMP / "test.db")
os.environ["LLM_STYLE_IMAGES_DIR"] = str(_TMP / "images")
os.environ["LLM_STYLE_DATA_DIR"] = str(_TMP)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.categories import default_category  # noqa: E402
from app.config import AppConfig  # noqa: E402
from app.main import create_app  # noqa: E402
from app.db import init_db  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


@pytest.fixture()
def config(tmp_path):
    return AppConfig(db_path=tmp_path / "test.db")


def make_item(id_, type_, warmth, formality, color="black", name=None, tags=None,
              category=None):
    return {
        "id": id_,
        "name": name or f"{type_}-{id_}",
        "type": type_,
        "category": category or default_category(type_),
        "color": color,
        "warmth": warmth,
        "formality": formality,
        "style_tags": tags,
        "notes": None,
        "times_worn": 0,
    }


def full_wardrobe():
    """A wardrobe that covers all slots at varied warmth/formality."""
    items = []
    next_id = 1
    specs = {
        "top": [(1, 1), (1, 2), (2, 2), (3, 3), (4, 4), (5, 5), (2, 4), (3, 5)],
        "bottom": [(1, 1), (2, 2), (3, 2), (3, 3), (4, 4), (5, 4), (1, 3), (4, 5)],
        "shoes": [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (2, 3), (3, 4), (1, 2)],
        "outerwear": [(3, 2), (4, 3), (5, 3), (4, 4), (5, 4)],
        "accessory": [(1, 2), (2, 2), (3, 3), (4, 4), (1, 4), (2, 5)],
    }
    for type_, entries in specs.items():
        for warmth, formality in entries:
            items.append(make_item(next_id, type_, warmth, formality))
            next_id += 1
    return items


class ScriptedProvider:
    """Fake LlmProvider returning queued replies (or raising)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def complete(self, messages, model, temperature=0.7):
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("ScriptedProvider ran out of scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeWeatherService:
    """WeatherService double with a fixed temperature."""

    def __init__(self, temp_c=20.0, fail=False):
        self.temp_c = temp_c
        self.fail = fail

    def current(self, city):
        if self.fail:
            from app.services.weather import WeatherUnavailable

            raise WeatherUnavailable("network down")
        from app.models import Weather

        return Weather(
            city=city,
            temperature_c=self.temp_c,
            apparent_temperature_c=self.temp_c,
            precipitation_mm=0.0,
            wind_speed_kmh=0.0,
            weather_code=0,
            fetched_at="2026-01-01T00:00:00+00:00",
        )


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """FastAPI TestClient with lifespan run (app.state populated).

    Images go to the test dir; the fake provider seam is the public
    provider_for method (no private-attribute patching).
    """
    monkeypatch.setattr(
        "app.services.images.IMAGES_DIR", tmp_path / "images", raising=True
    )
    cfg = AppConfig(db_path=tmp_path / "api.db")
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client, app
