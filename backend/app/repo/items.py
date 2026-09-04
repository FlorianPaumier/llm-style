"""Wardrobe items repository."""
from __future__ import annotations

import sqlite3

from ..models import ItemIn

_INSERT = """
INSERT INTO items (name, type, color, warmth, formality, style_tags, notes, image_path)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
_SELECT_ALL = "SELECT * FROM items ORDER BY id"
_SELECT_BY_ID = "SELECT * FROM items WHERE id = ?"
_SELECT_BY_IDS = "SELECT * FROM items WHERE id IN ({placeholders})"
_UPDATE = """
UPDATE items SET name = ?, type = ?, color = ?, warmth = ?, formality = ?,
                  style_tags = ?, notes = ?, image_path = ?
WHERE id = ?
"""
_DELETE = "DELETE FROM items WHERE id = ?"
_UPDATE_IMAGE = "UPDATE items SET image_path = ? WHERE id = ?"


def create(conn: sqlite3.Connection, item: ItemIn) -> dict:
    cur = conn.execute(
        _INSERT,
        (item.name, item.type, item.color, item.warmth, item.formality,
         item.style_tags, item.notes, item.image_path),
    )
    conn.commit()
    return get(conn, cur.lastrowid)


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(_SELECT_ALL)]


def get(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(_SELECT_BY_ID, (item_id,)).fetchone()
    return dict(row) if row else None


def get_many(conn: sqlite3.Connection, item_ids: list[int]) -> list[dict]:
    if not item_ids:
        return []
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(_SELECT_BY_IDS.format(placeholders=placeholders), item_ids)
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[i] for i in item_ids if i in by_id]


def update(conn: sqlite3.Connection, item_id: int, item: ItemIn) -> dict | None:
    if get(conn, item_id) is None:
        return None
    conn.execute(
        _UPDATE,
        (item.name, item.type, item.color, item.warmth, item.formality,
         item.style_tags, item.notes, item.image_path, item_id),
    )
    conn.commit()
    return get(conn, item_id)


def delete(conn: sqlite3.Connection, item_id: int) -> bool:
    cur = conn.execute(_DELETE, (item_id,))
    conn.commit()
    return cur.rowcount > 0


def update_image_path(conn: sqlite3.Connection, item_id: int, image_path: str | None) -> None:
    conn.execute(_UPDATE_IMAGE, (image_path, item_id))
    conn.commit()
