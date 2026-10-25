"""Wardrobe items repository."""
from __future__ import annotations

import sqlite3

from ..categories import default_category
from ..models import Item, ItemIn, ItemSortKey, ItemUpdate

_INSERT = """
INSERT INTO items (name, type, category, color, warmth, formality, style_tags, notes, image_path, persona_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
"""
_SELECT_BY_ID = "SELECT * FROM items WHERE id = ?"
_SELECT_BY_IDS = "SELECT * FROM items WHERE id IN ({placeholders})"
# Update never touches image_path: photos are managed via claim/remove so a
# field edit can't silently orphan the photo file.
_UPDATE = """
UPDATE items SET name = ?, type = ?, category = ?, color = ?, warmth = ?, formality = ?,
                  style_tags = ?, notes = ?, persona_id = ?
WHERE id = ?
"""
_DELETE = "DELETE FROM items WHERE id = ?"
_UPDATE_IMAGE = "UPDATE items SET image_path = ? WHERE id = ?"
_INCREMENT_WORN = "UPDATE items SET times_worn = times_worn + 1 WHERE id IN ({ids})"

# Whitelist: sort keys map to columns, never interpolated raw.
_SORT_COLUMNS = {
    "name": "name COLLATE NOCASE",
    "type": "type",
    "category": "category COLLATE NOCASE",
    "color": "color COLLATE NOCASE",
    "warmth": "warmth",
    "formality": "formality",
    "style_tags": "style_tags COLLATE NOCASE",
}


def _normalize(row: dict) -> dict:
    """Give rows written without a category (pre-backfill or raw SQL)
    their slot's catch-all so every read path sees a concrete category."""
    if not row.get("category"):
        row["category"] = default_category(row["type"])
    return row


def to_item(row: dict) -> Item:
    """Build the API-facing Item: photo addressed as a URL, never a path."""
    has_photo = bool(row.get("image_path"))
    return Item(
        name=row["name"],
        type=row["type"],
        category=_normalize(row)["category"],
        color=row["color"],
        warmth=row["warmth"],
        formality=row["formality"],
        style_tags=row["style_tags"],
        notes=row["notes"],
        id=row["id"],
        times_worn=row.get("times_worn") or 0,
        persona_id=row.get("persona_id") or 1,
        has_photo=has_photo,
        photo_url=f"/api/items/{row['id']}/photo" if has_photo else None,
    )


def create(conn: sqlite3.Connection, item: ItemIn, persona_id: int | None = None) -> dict:
    cur = conn.execute(
        _INSERT,
        (item.name, item.type, item.category, item.color, item.warmth, item.formality,
         item.style_tags, item.notes, persona_id or 1),
    )
    conn.commit()
    return get(conn, cur.lastrowid)


def list_all(conn: sqlite3.Connection, persona_id: int | None = None) -> list[dict]:
    """Every item, optionally one persona's — the recommender scans whole
    wardrobes. persona_id None = unfiltered (all wardrobes)."""
    if persona_id is None:
        rows = conn.execute("SELECT * FROM items ORDER BY id")
    else:
        rows = conn.execute(
            "SELECT * FROM items WHERE persona_id = ? ORDER BY id", (persona_id,)
        )
    return [_normalize(dict(r)) for r in rows]


def get(conn: sqlite3.Connection, item_id: int) -> dict | None:
    row = conn.execute(_SELECT_BY_ID, (item_id,)).fetchone()
    return _normalize(dict(row)) if row else None


def get_many(conn: sqlite3.Connection, item_ids: list[int]) -> list[dict]:
    if not item_ids:
        return []
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(_SELECT_BY_IDS.format(placeholders=placeholders), item_ids)
    by_id = {row["id"]: _normalize(dict(row)) for row in rows}
    return [by_id[i] for i in item_ids if i in by_id]


def update(conn: sqlite3.Connection, item_id: int, item: ItemUpdate) -> dict | None:
    if get(conn, item_id) is None:
        return None
    # persona_id moves the item between wardrobes when the client sends it;
    # omitting the field keeps the item where it is.
    current = get(conn, item_id)
    target_persona = item.persona_id if item.persona_id is not None else current["persona_id"]
    conn.execute(
        _UPDATE,
        (item.name, item.type, item.category, item.color, item.warmth, item.formality,
         item.style_tags, item.notes, target_persona, item_id),
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


def increment_worn(conn: sqlite3.Connection, item_ids: list[int]) -> None:
    if not item_ids:
        return
    placeholders = ",".join("?" * len(item_ids))
    conn.execute(_INCREMENT_WORN.format(ids=placeholders), item_ids)
    conn.commit()


def query(
    conn: sqlite3.Connection,
    *,
    persona_id: int | None = None,
    type: str | None = None,
    warmth: int | None = None,
    formality: int | None = None,
    q: str | None = None,
    sort: ItemSortKey | None = None,
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Filtered/sorted/paged item query; returns (rows, total)."""
    where: list[str] = []
    params: list = []
    if persona_id is not None:
        where.append("persona_id = ?")
        params.append(persona_id)
    if type:
        where.append("type = ?")
        params.append(type)
    if warmth is not None:
        where.append("warmth = ?")
        params.append(warmth)
    if formality is not None:
        where.append("formality = ?")
        params.append(formality)
    if q:
        where.append("(name LIKE ? OR color LIKE ? OR style_tags LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(
        "SELECT COUNT(*) AS n FROM items" + clause, params
    ).fetchone()["n"]

    order_sql = " ORDER BY id"
    if sort:
        direction = "ASC" if order == "asc" else "DESC"
        order_sql = f" ORDER BY {_SORT_COLUMNS[sort]} {direction}, id"
    rows = conn.execute(
        "SELECT * FROM items" + clause + order_sql + " LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return [_normalize(dict(r)) for r in rows], total
