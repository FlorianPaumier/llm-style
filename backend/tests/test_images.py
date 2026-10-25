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
    token = images.save_draft_image(data, ".jpg")
    assert token.startswith("draft-") and token.endswith(".jpg")
    assert images.photo_path(token).exists()

    # Claim for item 7: renamed to the item id.
    final = images.claim_image(token, 7)
    assert final == "7.jpg"
    assert (images_tmp / "7.jpg").exists()
    assert not images.photo_path(token).exists()

    # Delete: file removed, no error when path is None or already gone.
    images.delete_image(final)
    assert not (images_tmp / "7.jpg").exists()
    images.delete_image(None)
    images.delete_image(final)  # already gone: still fine


def test_claim_is_idempotent(images_tmp):
    images_tmp.mkdir(parents=True, exist_ok=True)
    existing = images_tmp / "7.jpg"
    existing.write_bytes(b"x")
    assert images.claim_image("7.jpg", 7) == "7.jpg"


def test_claim_rejects_foreign_names(images_tmp):
    images_tmp.mkdir(parents=True, exist_ok=True)
    # A draft token that doesn't look like ours.
    (images_tmp / "notadraft.txt").write_bytes(b"x")
    assert images.claim_image("notadraft.txt", 7) is None
    assert images.claim_image("8.jpg", 7) is None  # belongs to another item
    assert images.claim_image("", 7) is None


def test_photo_path_refuses_traversal_and_outside(images_tmp, tmp_path):
    for bad in ("/etc/hosts", "../../etc/hosts", "sub/dir/7.png", "7.png/../x",
                "draft-short.png", "C:\\win.ini", "\x007.png"):
        assert images.photo_path(bad) is None, bad
    # Only names matching the strict pattern resolve inside the images dir.
    p = images.photo_path("7.png")
    assert p == images_tmp / "7.png"
    assert images.photo_path("draft-0123456789ab.jpg") == images_tmp / "draft-0123456789ab.jpg"


def test_delete_refuses_paths_outside_images_dir(images_tmp, tmp_path):
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"x")
    images.delete_image(str(outside))
    assert outside.exists()  # untouched: pattern refused, not our directory


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
