# llm-style

Tell it your mood; it tells you what to wear — from **your** wardrobe, matched to today's weather and your occasion.

A personal, local-first app: your wardrobe data and the reasoning stay on your machine. A small LLM (via [Ollama](https://ollama.com)) acts as the stylist; a deterministic engine does the heavy filtering so the model only makes the final judgment call.

## How it works

```
mood + occasion ──┐
weather (Open-Meteo) ──┤
wardrobe (SQLite) ──┴─> CandidateSelector ──> ~20 candidates ──> LLM stylist ──> outfit + rationale
                     (deterministic rules)    (warmth/formality/slots)  (mood judgment, validated)
```

- **CandidateSelector** narrows the wardrobe by weather-driven warmth bands and occasion-driven formality bands, guarantees every clothing slot is covered, and relaxes constraints when the wardrobe can't. This keeps the prompt small — a 3–8B model stays reliable.
- **LLM stylist** sees only the compact candidate list plus your mood, picks one outfit, and explains why it fits. Answers are validated (IDs must be real candidates); a bad answer gets one retry, then a deterministic safe pick.
- **Photo classification**: drop a photo of a clothing item on the Wardrobe page and a vision model (`gemma3:4b`) drafts the item — name, type, color, warmth, formality, style tags — into the form for you to review and save. The draft is a suggestion, not the truth: misjudged warmth/formality would silently skew recommendations, so you always give the final glance before saving. Photos are stored locally under `data/images/` and shown as thumbnails.
- Everything degrades gracefully: no weather → mild-day assumption (or manual override); no Ollama → fallback outfit with a note; missing slots → a named gap telling you what to buy.

## Setup

Prerequisites: Python 3.11+, [Ollama](https://ollama.com) with a small model pulled.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# pull the two models (stylist + vision; or change them in Settings)
ollama pull dolphin-mistral:7b
ollama pull gemma3:4b

# optional: sample wardrobe (31 items) so you can try it immediately
.venv/bin/python ../scripts/seed_wardrobe.py

# run
.venv/bin/uvicorn app.main:app
```

Open http://localhost:8000 — three pages: **Ask** (mood → outfit), **Wardrobe** (CRUD + photo classification), **Settings** (city, models, Ollama URL).

> First request after pulling a model can take ~10–30s while Ollama loads it into memory; subsequent calls are fast. Photo classification takes ~20s per photo on an M1.

## Wardrobe items

Each item has: name, type (top/bottom/shoes/outerwear/accessory), color, warmth 1–5 (1 = light), formality 1–5 (1 = gym, 5 = black tie), style tags, notes.

## Tests

```bash
cd backend
.venv/bin/python -m pytest              # unit + service + API tests (offline)
.venv/bin/python -m pytest -m integration  # real Ollama round-trip (opt-in)
```

## Configuration

Defaults via env vars: `LLM_STYLE_DB`, `LLM_STYLE_CITY` (Paris), `LLM_STYLE_MODEL` (dolphin-mistral:7b), `LLM_STYLE_VISION_MODEL` (gemma3:4b), `LLM_STYLE_OLLAMA_URL`. The Settings page overrides them per instance.

## Project layout

```
backend/app/         FastAPI app: main.py, models, db, repo/, services/, llm/
backend/tests/       pytest suite (fakes for weather + LLM; integration opt-in)
frontend/            static HTML/CSS/JS — no build step, served by the backend
scripts/             seed_wardrobe.py
```
