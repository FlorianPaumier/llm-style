"""Image storage: uploaded wardrobe photos live under data/images/.

Photos are addressed by opaque tokens, never filesystem paths:
- /api/classify saves a draft photo and returns its token (draft-<hex>.<ext>).
- Saving the item claims the token: the file is renamed to <item_id>.<ext>.
- Every read/delete resolves the stored name strictly inside IMAGES_DIR,
  so a client-supplied string can never point outside the images dir.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

from ..config import DATA_DIR

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# A stored photo name is either a fresh draft (from /api/classify) or an
# item's claimed file; the regex has no separators or traversal, so names
# can only ever resolve inside the images dir.
PHOTO_NAME_RE = re.compile(r"^(?:draft-[0-9a-f]{12}|\d+)\.(?:jpg|jpeg|png|webp)$")

# Overridable so tests store images in a temp dir instead of real data/.
IMAGES_DIR = Path(os.environ.get("LLM_STYLE_IMAGES_DIR", str(DATA_DIR / "images")))


def images_dir() -> Path:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return IMAGES_DIR


def validate_extension(filename: str) -> str:
    """Return the lowercase extension of an allowed image filename, else ''."""
    ext = Path(filename).suffix.lower()
    return ext if ext in ALLOWED_EXTENSIONS else ""


def photo_path(name: str | None) -> Path | None:
    """Resolve a stored photo name to a path inside IMAGES_DIR, or None."""
    if not name or not PHOTO_NAME_RE.match(name):
        return None
    return images_dir() / name


def draft_exists(token: str) -> bool:
    """True if token refers to a draft photo still on disk."""
    if not token.startswith("draft-"):
        return False
    path = photo_path(token)
    return path is not None and path.is_file()


def save_draft_image(data: bytes, ext: str) -> str:
    """Persist an uploaded photo for a not-yet-created item; return its token."""
    token = f"draft-{uuid.uuid4().hex[:12]}{ext}"
    (images_dir() / token).write_bytes(data)
    return token


def claim_image(token: str, item_id: int) -> str | None:
    """Rename draft-<hex>.<ext> to <item_id>.<ext> once the item exists.

    Returns the final stored name, or None if the token is not a live draft
    for this item. Idempotent for a name already owned by the item; refuses
    any name belonging to anything else.
    """
    if not token or not PHOTO_NAME_RE.match(token):
        return None
    ext = Path(token).suffix.lower()
    final = f"{item_id}{ext}"
    if token.startswith("draft-"):
        src = images_dir() / token
        dst = images_dir() / final
        if src.is_file():
            src.rename(dst)
        elif not dst.is_file():
            return None
        return final
    return token if token == final else None


def delete_image(name: str | None) -> None:
    """Remove an item's photo file, if it lives in our images dir."""
    path = photo_path(name)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
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
