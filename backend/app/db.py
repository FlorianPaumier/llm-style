"""SQLite connection management and schema initialization."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

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
    "ALTER TABLE outfit_history ADD COLUMN worn_at TEXT",
    "ALTER TABLE items ADD COLUMN persona_id INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE outfit_history ADD COLUMN persona_id INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE personas ADD COLUMN description TEXT",
    "ALTER TABLE items ADD COLUMN category TEXT",
    "ALTER TABLE personas ADD COLUMN gender TEXT",
]

# Backfill for the additive `category` column: rows written before the
# column existed (or via raw SQL that skipped it) get their slot's
# catch-all category. Idempotent: only NULL/blank rows are touched.
_CATEGORY_BACKFILL = (
    "UPDATE items SET category = 'other_' || type "
    "WHERE category IS NULL OR category = ''"
)


def connect(db_path: Path | str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI resolves dependencies and endpoints on
    # different worker threads; each request/job uses its own connection and
    # never concurrently, and WAL + busy_timeout serializes writers.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL + busy timeout: a second client (e.g. a phone on the LAN) writing
    # concurrently must not surface "database is locked".
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: Path | str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        # Single-row/persona tables: seed defaults once.
        conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
        conn.execute("INSERT OR IGNORE INTO personas (id, name) VALUES (1, 'Me')")
        for sql in MIGRATIONS:
            try:
                conn.execute(sql)  # duplicate column -> already migrated
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc):
                    raise
        _shorten_image_paths(conn)
        conn.execute(_CATEGORY_BACKFILL)
        conn.commit()
    finally:
        conn.close()


def _shorten_image_paths(conn: sqlite3.Connection) -> None:
    """Older databases stored absolute photo paths; photos are now addressed
    by filename only, inside the images dir. Idempotent."""
    rows = conn.execute(
        "SELECT id, image_path FROM items WHERE image_path IS NOT NULL"
    ).fetchall()
    for row in rows:
        stored = row["image_path"]
        base = os.path.basename(stored.replace("\\", "/"))
        if base != stored:
            conn.execute(
                "UPDATE items SET image_path = ? WHERE id = ?", (base, row["id"])
            )
