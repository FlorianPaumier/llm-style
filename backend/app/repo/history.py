"""Outfit history repository."""
from __future__ import annotations

import json
import sqlite3

_INSERT = """
INSERT INTO outfit_history (mood, occasion, weather_json, item_ids_json, rationale, source, persona_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""
_SELECT_RECENT = "SELECT * FROM outfit_history{where} ORDER BY id DESC LIMIT ?"
_SELECT_BY_ID = "SELECT * FROM outfit_history WHERE id = ?"
_MARK_WORN = "UPDATE outfit_history SET worn_at = ? WHERE id = ?"


def add(
    conn: sqlite3.Connection,
    mood: str,
    occasion: str,
    weather: dict | None,
    item_ids: list[int],
    rationale: str,
    source: str,
    persona_id: int = 1,
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
            persona_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def recent(
    conn: sqlite3.Connection, limit: int = 20, persona_id: int | None = None
) -> list[dict]:
    where, params = "", []
    if persona_id is not None:
        where = " WHERE persona_id = ?"
        params = [persona_id]
    rows = conn.execute(
        _SELECT_RECENT.format(where=where), params + [limit]
    )
    return [dict(r) for r in rows]


def get(conn: sqlite3.Connection, history_id: int) -> dict | None:
    row = conn.execute(_SELECT_BY_ID, (history_id,)).fetchone()
    return dict(row) if row else None


def mark_worn(conn: sqlite3.Connection, history_id: int, worn_at: str) -> None:
    conn.execute(_MARK_WORN, (worn_at, history_id))
    conn.commit()


def recent_item_ids(
    conn: sqlite3.Connection, persona_id: int, limit: int = 3
) -> list[list[int]]:
    """The last `limit` outfits' item-id lists for one persona, oldest first.

    Variety memory: what the stylist recently SUGGESTED (suggested-but-
    unworn options must still be avoided, so times_worn is not the signal).
    """
    rows = recent(conn, limit=limit, persona_id=persona_id)
    out = []
    for row in reversed(rows):  # recent() is newest-first; prompt wants oldest-first
        try:
            ids = json.loads(row["item_ids_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(ids, list) and ids:
            out.append([int(i) for i in ids])
    return out
