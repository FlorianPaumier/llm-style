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
    default_model: str = "gemma3:12b"
    default_ollama_url: str = "http://localhost:11434"


def load_config() -> AppConfig:
    db_path = Path(os.environ.get("LLM_STYLE_DB", DATA_DIR / "llm_style.db"))
    return AppConfig(
        db_path=db_path,
        default_city=os.environ.get("LLM_STYLE_CITY", "Paris"),
        default_model=os.environ.get("LLM_STYLE_MODEL", "gemma3:12b"),
        default_ollama_url=os.environ.get("LLM_STYLE_OLLAMA_URL", "http://localhost:11434"),
    )
