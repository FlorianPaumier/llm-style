"""App configuration: paths and defaults, overridable via env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("LLM_STYLE_DATA_DIR", PROJECT_ROOT / "data"))


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    default_city: str = "Paris"
    default_model: str = "dolphin-mistral:7b"
    default_ollama_url: str = "http://localhost:11434"
    default_vision_model: str = "gemma3:4b"
    # Origins allowed to call the API cross-origin (mobile webviews etc.).
    # Default: any — the app binds to localhost/LAN and has no auth to bypass.
    cors_origins: tuple[str, ...] = ("*",)


def load_config() -> AppConfig:
    db_path = Path(os.environ.get("LLM_STYLE_DB", DATA_DIR / "llm_style.db"))
    cors = os.environ.get("LLM_STYLE_CORS_ORIGINS", "*")
    return AppConfig(
        db_path=db_path,
        default_city=os.environ.get("LLM_STYLE_CITY", "Paris"),
        default_model=os.environ.get("LLM_STYLE_MODEL", "dolphin-mistral:7b"),
        default_ollama_url=os.environ.get("LLM_STYLE_OLLAMA_URL", "http://localhost:11434"),
        default_vision_model=os.environ.get("LLM_STYLE_VISION_MODEL", "gemma3:4b"),
        cors_origins=tuple(o.strip() for o in cors.split(",") if o.strip()),
    )
