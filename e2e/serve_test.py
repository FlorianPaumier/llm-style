#!/usr/bin/env python3
"""Isolated backend launcher for the Playwright e2e suite.

Runs the real FastAPI app (backend/app) against throwaway data so the
tests NEVER touch the user's real database or photos:

- LLM_STYLE_DB          -> /tmp/llm-style-e2e/<name>.db
- LLM_STYLE_IMAGES_DIR  -> /tmp/llm-style-e2e/<name>/images
- LLM_STYLE_DATA_DIR    -> /tmp/llm-style-e2e/<name>

Env vars are set BEFORE app.main is imported (the images module reads
LLM_STYLE_IMAGES_DIR at import time). The data dir name is unique per
run by default ($LLM_STYLE_E2E_NAME or a UUID); pass --fresh to reuse
/tmp/llm-style-e2e/default instead (one throwaway DB for the run, as
Playwright's webServer starts the process once).

Usage (from the repo root):
  backend/.venv/bin/python e2e/serve_test.py --port 8799 [--fresh]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="reuse the /tmp/llm-style-e2e/default dir (deleted first)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the throwaway dir after exit (default: delete it)",
    )
    args = parser.parse_args()

    if args.fresh:
        import shutil

        base = Path("/tmp/llm-style-e2e/default")
        if base.exists():
            shutil.rmtree(base)
        name = "default"
    else:
        name = os.environ.get("LLM_STYLE_E2E_NAME") or uuid.uuid4().hex[:8]
    base = Path("/tmp/llm-style-e2e") / name
    base.mkdir(parents=True, exist_ok=True)

    # Isolation, set before ANY app import (app.main creates the app and
    # app.services.images bakes IMAGES_DIR in at import time).
    os.environ["LLM_STYLE_DATA_DIR"] = str(base)
    os.environ["LLM_STYLE_DB"] = str(base / "llm_style.db")
    os.environ["LLM_STYLE_IMAGES_DIR"] = str(base / "images")

    sys.path.insert(0, str(REPO_ROOT / "backend"))

    import uvicorn

    from app.config import AppConfig, load_config
    from app.main import create_app

    config: AppConfig = load_config()
    real_db = REPO_ROOT / "data" / "llm_style.db"

    app = create_app(config)

    # Sanity check: our DB is the throwaway one, never the real data dir.
    if str(config.db_path) == str(real_db):
        print(f"REFUSING TO START: db path is the real DB {real_db}", file=sys.stderr)
        return 2
    print(f"[e2e] isolated DB: {config.db_path}", file=sys.stderr)
    print(f"[e2e] isolated images: {os.environ['LLM_STYLE_IMAGES_DIR']}", file=sys.stderr)
    print(f"[e2e] real DB untouched: {real_db}", file=sys.stderr)

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    finally:
        if not args.keep and name != "default":
            import shutil

            shutil.rmtree(base, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
