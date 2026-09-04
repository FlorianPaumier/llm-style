"""Settings repository: single-row table."""
from __future__ import annotations

import sqlite3

_SELECT = "SELECT * FROM settings WHERE id = 1"
_UPDATE = "UPDATE settings SET city = ?, model = ?, ollama_url = ? WHERE id = 1"


def get(conn: sqlite3.Connection) -> dict:
    row = conn.execute(_SELECT).fetchone()
    if row is None:
        conn.execute("INSERT INTO settings (id) VALUES (1)")
        conn.commit()
        row = conn.execute(_SELECT).fetchone()
    return dict(row)


def update(conn: sqlite3.Connection, city: str, model: str, ollama_url: str) -> dict:
    conn.execute(_UPDATE, (city, model, ollama_url))
    conn.commit()
    return get(conn)
