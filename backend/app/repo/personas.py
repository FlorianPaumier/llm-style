"""Personas repository: the people whose wardrobes the app dresses."""
from __future__ import annotations

import sqlite3

_SELECT_ALL = "SELECT * FROM personas ORDER BY id"
_SELECT_BY_ID = "SELECT * FROM personas WHERE id = ?"
_INSERT = "INSERT INTO personas (name, description, gender) VALUES (?, ?, ?)"
_DELETE = "DELETE FROM personas WHERE id = ?"


def _normalize(row: dict) -> dict:
    """Rows written before the gender column (or via raw SQL) read as
    unspecified instead of surfacing NULL."""
    row["gender"] = row.get("gender") or "unspecified"
    return row


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [_normalize(dict(r)) for r in conn.execute(_SELECT_ALL)]


def first(conn: sqlite3.Connection) -> dict:
    """The default persona — target of backward-compatible calls."""
    rows = list_all(conn)
    if not rows:  # DB predates personas; re-seed lazily.
        conn.execute("INSERT OR IGNORE INTO personas (id, name) VALUES (1, 'Me')")
        conn.commit()
        rows = list_all(conn)
    return rows[0]


def get(conn: sqlite3.Connection, persona_id: int) -> dict | None:
    row = conn.execute(_SELECT_BY_ID, (persona_id,)).fetchone()
    return _normalize(dict(row)) if row else None


def create(
    conn: sqlite3.Connection,
    name: str,
    description: str | None = None,
    gender: str | None = None,
) -> dict:
    cur = conn.execute(
        _INSERT, (name, description, gender or "unspecified")
    )
    conn.commit()
    return get(conn, cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    persona_id: int,
    name: str | None = None,
    description: str | None = None,
    gender: str | None = None,
) -> dict | None:
    """Set the provided fields; None leaves a field unchanged. Use
    update_description to clear (None and '' both become SQL NULL)."""
    if get(conn, persona_id) is None:
        return None
    assignments = []
    params: list = []
    if name is not None:
        assignments.append("name = ?")
        params.append(name)
    if description is not None:
        assignments.append("description = ?")
        params.append(description)
    if gender is not None:
        assignments.append("gender = ?")
        params.append(gender)
    if assignments:
        conn.execute(
            f"UPDATE personas SET {', '.join(assignments)} WHERE id = ?",
            (*params, persona_id),
        )
        conn.commit()
    return get(conn, persona_id)


def rename(conn: sqlite3.Connection, persona_id: int, name: str) -> dict | None:
    """Backward-compatible shorthand for update(name=...)."""
    return update(conn, persona_id, name=name)


def update_description(
    conn: sqlite3.Connection, persona_id: int, description: str | None
) -> dict | None:
    """Set the description; None or '' clears it to SQL NULL."""
    if get(conn, persona_id) is None:
        return None
    conn.execute(
        "UPDATE personas SET description = ? WHERE id = ?",
        (description if description else None, persona_id),
    )
    conn.commit()
    return get(conn, persona_id)


def delete(conn: sqlite3.Connection, persona_id: int) -> bool:
    cur = conn.execute(_DELETE, (persona_id,))
    conn.commit()
    return cur.rowcount > 0


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM personas").fetchone()["n"]
