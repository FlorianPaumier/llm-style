"""Routes for quick add: photo in, saved item out (no review form).

Kept in its own module (repo style is one register_* function per area) so
main.py only needs one import + one registration line. The sync endpoint
mirrors /api/classify's validation and error mapping, duplicated on purpose
so this area stays independent of the classify route's internals.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from . import repo
from .models import QuickAddResponse
from .services import classify, images, quickadd


def register_quickadd_routes(app: FastAPI, get_conn) -> None:
    async def read_upload(photo: UploadFile) -> tuple[bytes, str]:
        """Same validation rules as /api/classify, kept local on purpose."""
        ext = images.validate_extension(photo.filename or "")
        if not ext:
            raise HTTPException(422, "Photo must be .jpg, .jpeg, .png or .webp")
        data = await photo.read()
        if not data:
            raise HTTPException(422, "Empty upload")
        if len(data) > images.MAX_IMAGE_BYTES:
            raise HTTPException(413, "Photo must be under 10 MB")
        return data, ext

    @app.post("/api/items/from-photo", response_model=QuickAddResponse, status_code=201)
    async def item_from_photo(
        photo: UploadFile = File(...),
        persona_id: int | None = Form(None),
        conn=Depends(get_conn),
    ):
        """Photograph -> classified items saved immediately, no draft form.

        The vision model's drafts ARE the items (trust the draft) — a
        flat-lay with several garments saves one item per garment, each
        with its own copy of the photo. The blocking classify call runs
        in the threadpool like /api/classify so polling and other
        requests stay responsive.
        """
        data, ext = await read_upload(photo)
        persona = None
        if persona_id is not None:
            persona = repo.personas.get(conn, persona_id)
            if persona is None:
                raise HTTPException(422, f"Unknown persona id {persona_id}")
        try:
            return await run_in_threadpool(
                quickadd.quick_add,
                conn,
                photo_bytes=data,
                ext=ext,
                persona_id=persona["id"] if persona else None,
                provider_factory=app.state.recommender.provider_for,
                config=app.state.config,
            )
        except classify.ClassificationError as exc:
            raise HTTPException(503, f"Vision model unavailable: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(503, f"Vision model returned unusable output: {exc}") from exc
