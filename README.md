# llm-style

The C# / Blazor implementation with shared web and Apple Silicon / Windows desktop hosts is in [dotnet/](dotnet/README.md). Its [migration plan](docs/superpowers/plans/2026-10-20-csharp-blazor-desktop.md) uses DDD, Clean Architecture and TDD. The Python application below remains the working product during migration.

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
- **No repeats, more options**: re-asking the same prompt won't give you the same outfit — the stylist is shown the last few suggested combinations with a rule to vary, the candidate sample is re-drawn per request, and the safe fallback rotates toward unexplored pieces (a small wardrobe still repeats when it must). The Ask page's "How many options?" select (1/3/5) asks for several distinct outfits in one go; each option knows the ones before it, and "We wore this today" marks just the option you actually wore.
- **Photo classification**: drop a photo of a clothing item on the Wardrobe page and a vision model (`gemma3:4b`) drafts the item — name, type, color, warmth, formality, style tags — into the form for you to review and save. **One photo can hold several items**: a flat-lay (all the clothes of an outfit on the bed, for instance) returns one draft per piece — up to 8 — which appear as one row per item in the review queue; single-item photos still go straight into the form. The draft is a suggestion, not the truth: misjudged warmth/formality would silently skew recommendations, so you always give the final glance before saving. Photos are stored locally under `data/images/` and shown as thumbnails.
- **Bulk photo queue**: drop *several* photos at once and they queue up — each is classified one at a time (never a burst of model calls), with per-photo status and a "Review" button to load each draft into the form. A photo that fails doesn't stop the queue, and a multi-item photo expands into one row per item once its result lands. A **Save all** button saves every ready draft in one click. There is no limit on how many photos you drop: uploads beyond the backend's 20-per-request cap are sent as sequential batches, still one model call at a time.
- **Quick add**: for speed over certainty, tick "Save without review" — the photo is drafted *and* saved straight into the chosen wardrobe, no form at all; every item the model detects in the photo is saved (a flat-lay can add several items in one go).
- **Accessories are first-class**: hats, scarves, belts and watches are matched to the weather like the rest of the outfit — no wool beanie on a 30°C day (band-matched, relaxed only with a note when the wardrobe has nothing better, and skipped by the fallback stylist when nothing suits the temperature). The LLM is told to use judgment: skip accessories that don't fit the weather, the occasion, or the person's notes.
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

# optional: sample wardrobe (500 items split across two personas, "Me" and
# "Partner") so you can try single and pair recommendations immediately
.venv/bin/python ../scripts/seed_wardrobe.py

# run
.venv/bin/uvicorn app.main:app
```

Open http://localhost:8000 — three pages: **Ask** (mood → outfit), **Wardrobe** (CRUD + photo classification), **Settings** (city, models, Ollama URL).

## Several people, one app (personas)

The wardrobe can hold several people — e.g. you and your partner, each with
their own clothes and outfit history. Manage people on the **Settings** page
("People" — name plus optional **styling notes** the LLM must respect, like
*"no hats — they don't suit me"*); switch whose wardrobe you're viewing on the
**Wardrobe** page (the item form also has a "Whose wardrobe?" picker, so each
item lands in — or can move between — the right wardrobe). On the **Ask** page
the chips are multi-select: pick one person for a normal recommendation, or
**select both for pair mode** — the stylist proposes one outfit each,
coordinated (complementary colors and dressiness, no doubled statement
pieces), from one shared weather fetch. Persona settings (city, models) are
shared; only wardrobes and history are per person.

## On your phone (easy download)

The app is a PWA — it installs like a native app, no App Store:

```bash
# expose the server on your Wi-Fi (phones can't reach 127.0.0.1)
.venv/bin/uvicorn app.main:app --host 0.0.0.0
```

Open **Get the app** in the header (or http://localhost:8000/install.html): it shows a **QR code** encoding your machine's Wi-Fi address. Scan it with your phone, then "Add to Home Screen" (iOS) or "Install app" (Android). The app then sits on your home screen with its own icon, fullscreen, and keeps working offline-ish (the UI shell caches; live data needs the backend running).

The same info is available to any client as JSON: `GET /api/app/download` — see [MOBILE_API.md](MOBILE_API.md) for the full mobile API (pagination, async jobs, worn tracking, CORS, photo tokens).

> First request after pulling a model can take ~10–30s while Ollama loads it into memory; subsequent calls are fast. Photo classification takes ~20s per photo on an M1.

## Wardrobe items

Each item has: name, category (the detailed classification — e.g. `t_shirt`, `dress`, `cardigan`, `trench_coat`, `tights`), type (the broad slot derived from it: top/bottom/shoes/outerwear/accessory), color, warmth 1–5 (1 = light), formality 1–5 (1 = gym, 5 = black tie), style tags, notes.

The category drives outfit compatibility: one primary top (or a one-piece dress/jumpsuit/romper), at most one layer (cardigan) over it, one primary bottom, optional tights/leggings under a skirt, dress or shorts, one pair of shoes. The vision classifier drafts the category too, and the wardrobe form makes it the primary selector.

## Tests

```bash
cd backend
.venv/bin/python -m pytest              # unit + service + API tests (offline)
.venv/bin/python -m pytest -m integration  # real Ollama round-trip (opt-in)

# end-to-end browser tests (Playwright; isolated temp server, never touches data/)
cd ../e2e && npm install && npx playwright install chromium && npx playwright test
```

## Configuration

Defaults via env vars: `LLM_STYLE_DB`, `LLM_STYLE_CITY` (Paris), `LLM_STYLE_MODEL` (dolphin-mistral:7b), `LLM_STYLE_VISION_MODEL` (gemma3:4b), `LLM_STYLE_OLLAMA_URL`. The Settings page overrides them per instance.

## Project layout

```
backend/app/         FastAPI app: main.py, models, db, repo/, services/, llm/
backend/tests/       pytest suite (fakes for weather + LLM; integration opt-in)
frontend/            static HTML/CSS/JS — no build step, served by the backend
  manifest.webmanifest, sw.js, icons/   PWA layer (installable app)
MOBILE_API.md        the mobile-facing API contract
scripts/             seed_wardrobe.py
```

## API notes (mobile-ready)

- Items list is paginated/filterable/sortable server-side: `GET /api/items?type=top&sort=warmth&order=desc&page=2`.
- Slow LLM endpoints have async job variants (`POST /api/outfits/recommend/async`, `POST /api/classify/async` → poll `GET /api/jobs/{id}`) for mobile networks.
- Multi-persona: `GET/POST /api/personas`; `?persona_id=` filters wardrobes; `persona_ids: [1,2]` on recommend returns coordinated `outfits` (one per person). Absent params = first persona, so old clients keep working.
- Photos are referenced by opaque server-issued tokens, never filesystem paths.
- CORS is open by default (`LLM_STYLE_CORS_ORIGINS` to restrict); SQLite runs in WAL mode for concurrent phone + desktop use.

## E2E tests

Playwright browser tests over the real app (`e2e/`), covering the core workflows: wardrobe CRUD (add/edit/delete with the confirm dialog), pagination/sort/filter, persona switching and pair-mode chips, the Ollama-down fallback recommendation, pair recommendations per person, "We wore this today" history marking, settings round-trip and persona delete guards, plus a data-isolation guard.

```bash
cd e2e
npm install                        # once
npx playwright install chromium    # once
npx playwright test                # starts its own backend on 127.0.0.1:8799
```

Key properties:

- **Isolation is sacred**: the suite starts `e2e/serve_test.py`, which points `LLM_STYLE_DB`, `LLM_STYLE_IMAGES_DIR` and `LLM_STYLE_DATA_DIR` at `/tmp/llm-style-e2e/` *before* the app is imported — your real `data/llm_style.db` and `data/images/` are never touched (asserted by `specs/isolation.spec.ts`).
- **No Ollama needed**: Ollama is expected to be down; the tests assert the deterministic fallback path (source `fallback`, safe-pick note, complete outfits from the seeded wardrobe).
- One shared backend per run, single worker; specs keep unique per-run names and wipe/seed the default wardrobe where the deterministic fallback's lowest-id tie-break must be unambiguous.
- Config knobs: `E2E_PORT` (default 8799) and `E2E_PYTHON` (default `backend/.venv/bin/python`) if your venv lives elsewhere.
