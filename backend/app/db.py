"""SQLite connection management and schema initialization."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('top', 'bottom', 'shoes', 'outerwear', 'accessory')),
    color TEXT,
    warmth INTEGER NOT NULL CHECK (warmth BETWEEN 1 AND 5),
    formality INTEGER NOT NULL CHECK (formality BETWEEN 1 AND 5),
    style_tags TEXT,
    notes TEXT,
    times_worn INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    city TEXT,
    model TEXT,
    ollama_url TEXT
);

CREATE TABLE IF NOT EXISTS outfit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    mood TEXT NOT NULL,
    occasion TEXT NOT NULL,
    weather_json TEXT,
    item_ids_json TEXT NOT NULL,
    rationale TEXT,
    source TEXT
);
"""

# Additive migrations for databases created before a column existed.
MIGRATIONS = [
    "ALTER TABLE items ADD COLUMN image_path TEXT",
    "ALTER TABLE settings ADD COLUMN vision_model TEXT",
]


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # Settings is a single-row table; seed the default row once.
        conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
        for sql in MIGRATIONS:
            try:
                conn.execute(sql)  # duplicate column -> already migrated
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc):
                    raise
        conn.commit()
    finally:
        conn.close()
