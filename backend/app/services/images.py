"""Image storage: save uploaded wardrobe photos under data/images/.

Files are named by item id (or a temp prefix while the item is still a
draft), stored with their original extension, and served back by the
API. Deleting an item also deletes its photo.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from ..config import DATA_DIR

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Overridable so tests store images in a temp dir instead of real data/.
IMAGES_DIR = Path(os.environ.get("LLM_STYLE_IMAGES_DIR", str(DATA_DIR / "images")))


def images_dir() -> Path:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return IMAGES_DIR


def validate_extension(filename: str) -> str:
    """Return the lowercase extension of an allowed image filename, else ''."""
    ext = Path(filename).suffix.lower()
    return ext if ext in ALLOWED_EXTENSIONS else ""


def save_draft_image(data: bytes, ext: str) -> Path:
    """Persist an uploaded photo for a not-yet-created item; returns its path."""
    target_dir = images_dir()
    unique = f"draft-{uuid.uuid4().hex[:12]}{ext}"
    path = target_dir / unique
    path.write_bytes(data)
    return path


def claim_image(draft_path: str | Path, item_id: int) -> str | None:
    """Rename draft-<uuid>.<ext> to <item_id>.<ext> once the item exists.

    Returns the final relative path (stored in the DB), or None if the
    draft path is missing/invalid. Idempotent: a path already named for
    the item is returned as-is.
    """
    draft = Path(draft_path)
    if not draft.name.startswith("draft-"):
        return str(draft)  # already claimed or externally provided

    ext = draft.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None
    final = images_dir() / f"{item_id}{ext}"
    if draft.exists():
        draft.rename(final)
    elif not final.exists():
        return None
    return str(final)


def delete_image(image_path: str | None) -> None:
    """Remove an item's photo file, if it lives in our images dir."""
    if not image_path:
        return
    path = Path(image_path)
    try:
        if path.parent.resolve() == images_dir().resolve() and path.exists():
            path.unlink()
    except (OSError, ValueError):
        pass  # best effort; a stray file is harmless


def sweep_stale_drafts(max_age_seconds: float = 24 * 3600) -> int:
    """Delete draft-* photos left by classify runs that never became items.

    Called at app startup; safe to run at any time since a live draft is
    at most minutes old, far under the day-long grace period.
    """
    removed = 0
    try:
        for path in images_dir().glob("draft-*"):
            try:
                if path.stat().st_mtime < time.time() - max_age_seconds:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed
