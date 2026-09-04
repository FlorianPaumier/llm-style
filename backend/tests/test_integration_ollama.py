"""Opt-in integration test: a real round-trip through a running Ollama.

Run with: pytest -m integration
Requires: `ollama serve` up, model from settings pulled (default dolphin-mistral:7b).
"""
import pytest

from app.services import stylist
from app.services.candidates import select

from conftest import full_wardrobe

pytestmark = pytest.mark.integration

OLLAMA_URL = "http://localhost:11434"
MODEL = "dolphin-mistral:7b"


def test_real_ollama_produces_valid_outfit():
    pytest.importorskip("httpx")
    import httpx

    from app.llm.provider import OllamaProvider

    try:
        provider = OllamaProvider(OLLAMA_URL, timeout=180.0, client=httpx.Client(timeout=180.0))
        candidates = select(full_wardrobe(), temp_c=12.0, occasion="casual", rng_seed=20260903)
        choice = stylist.choose(provider, MODEL, candidates, "cosy and relaxed", "casual")
    except stylist.StylistError as exc:
        pytest.skip(f"Ollama unavailable or model missing: {exc}")
    assert choice.source == "llm"
    assert {"top", "bottom", "shoes"} <= set(choice.slot_picks)
    assert choice.rationale
