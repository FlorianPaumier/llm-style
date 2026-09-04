"""Tests for image storage helpers (draft -> claim -> delete lifecycle)."""
import pytest

from app.services import images


@pytest.fixture()
def images_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "IMAGES_DIR", tmp_path / "images")
    return tmp_path / "images"


def test_validate_extension(images_tmp):
    assert images.validate_extension("photo.JPG") == ".jpg"
    assert images.validate_extension("photo.png") == ".png"
    assert images.validate_extension("photo.gif") == ""
    assert images.validate_extension("") == ""


def test_draft_save_claim_delete_lifecycle(images_tmp):
    data = b"\xff\xd8fakejpeg"
    draft_path = images.save_draft_image(data, ".jpg")
    assert draft_path.name.startswith("draft-")
    assert draft_path.exists()

    # Claim for item 7: renamed to the item id.
    final = images.claim_image(draft_path, 7)
    assert final == str(images_tmp / "7.jpg")
    assert (images_tmp / "7.jpg").exists()
    assert not draft_path.exists()

    # Delete: file removed, no error when path is None or already gone.
    images.delete_image(final)
    assert not (images_tmp / "7.jpg").exists()
    images.delete_image(None)
    images.delete_image(final)  # already gone: still fine


def test_claim_is_idempotent(images_tmp):
    (images_tmp).mkdir(parents=True, exist_ok=True)
    existing = images_tmp / "7.jpg"
    existing.write_bytes(b"x")
    assert images.claim_image(str(existing), 7) == str(existing)


def test_claim_rejects_bad_extension(images_tmp):
    draft = images_tmp / "draft-abc.exe"
    images_tmp.mkdir(parents=True, exist_ok=True)
    draft.write_bytes(b"x")
    assert images.claim_image(draft, 7) is None


def test_delete_refuses_paths_outside_images_dir(images_tmp, tmp_path):
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"x")
    images.delete_image(str(outside))
    assert outside.exists()  # untouched: not our directory


def test_sweep_stale_drafts_removes_only_old_drafts(images_tmp):
    import os
    import time

    images_tmp.mkdir(parents=True, exist_ok=True)
    old_draft = images_tmp / "draft-old.jpg"
    fresh_draft = images_tmp / "draft-fresh.jpg"
    claimed = images_tmp / "7.jpg"
    old_draft.write_bytes(b"old")
    fresh_draft.write_bytes(b"fresh")
    claimed.write_bytes(b"keep")
    # Age the old draft past the grace period.
    os.utime(old_draft, (time.time() - 25 * 3600,) * 2)

    removed = images.sweep_stale_drafts()

    assert removed == 1
    assert not old_draft.exists()
    assert fresh_draft.exists()  # still within grace
    assert claimed.exists()      # never a draft, never touched
