"""Outfit history repository."""
from __future__ import annotations

import json
import sqlite3

_INSERT = """
INSERT INTO outfit_history (mood, occasion, weather_json, item_ids_json, rationale, source)
VALUES (?, ?, ?, ?, ?, ?)
"""
_SELECT_RECENT = "SELECT * FROM outfit_history ORDER BY id DESC LIMIT ?"


def add(
    conn: sqlite3.Connection,
    mood: str,
    occasion: str,
    weather: dict | None,
    item_ids: list[int],
    rationale: str,
    source: str,
) -> int:
    cur = conn.execute(
        _INSERT,
        (
            mood,
            occasion,
            json.dumps(weather) if weather else None,
            json.dumps(item_ids),
            rationale,
            source,
        ),
    )
    conn.commit()
    return cur.lastrowid


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    return [dict(r) for r in conn.execute(_SELECT_RECENT, (limit,))]
