# Mobile API

The backend serves a mobile-ready HTTP API. Base URL: the machine running the
backend, e.g. `http://192.168.1.20:8000` (start it with
`uvicorn app.main:app --host 0.0.0.0` so the phone can reach it).

Conventions:

- **CORS** is open (`*`) by default; restrict with `LLM_STYLE_CORS_ORIGINS="https://app.example.tld"`.
- **Errors** always have the shape `{"detail": "..."}` (string). `422` from
  Pydantic may carry a list — treat `detail` as string-or-array.
- **Photos are opaque tokens**, never filesystem paths. `POST /api/classify`
  returns `{items: [DraftItem…]}`, each with its own `photo_token`; you send
  a token back when saving that item. Tokens are single-use-ish: a draft
  photo is claimed by the first item that saves it.
- **Long operations** (LLM calls, 10–60 s) have `.../async` variants returning
  `202 {job_id, status_url}` — poll `GET /api/jobs/{id}` every 1–2 s. Mobile
  HTTP stacks commonly time out at 30–60 s; prefer the async endpoints.

## Endpoints

### Wardrobe

| Method | Path | Notes |
|---|---|---|
| GET | `/api/items` | Query: `page` (1+), `page_size` (1–200, default 50), `type`, `warmth`, `formality`, `q` (name/color/tags search), `sort` (`name\|type\|category\|color\|warmth\|formality\|style_tags`), `order` (`asc\|desc`). Returns `{items, total, page, page_size, pages}`. |
| POST | `/api/items` | Body: `{name, category, color?, warmth, formality, style_tags?, notes?, photo_token?, persona_id?}` → `201` `Item`. `category` is required; `type` is derived from it and never needs to be sent — a `type` that is sent must agree with the category's broad slot or the request is `422`. |
| GET | `/api/items/{id}` | → `Item` |
| PUT | `/api/items/{id}` | Full field update (like POST: `category` required, `type` derived/validated). **Never touches the photo.** |
| DELETE | `/api/items/{id}` | `204`. Also deletes the photo file. |

`Item` = `{id, name, category, type, color, warmth, formality, style_tags, notes, times_worn, has_photo, photo_url}`.
`category` is the garment's detailed classification (e.g. `t_shirt`, `dress`, `trench_coat`); `type` is its broad recommendation slot (`top`, `bottom`, `shoes`, `outerwear`, `accessory`) derived from it — kept in every response so existing clients keep working. One-piece garments (`dress`, `jumpsuit`, `romper`) have type `top` and cover both the top and bottom of an outfit.
`photo_url` is a relative path (`/api/items/{id}/photo`) — prepend the base URL.

**Supported categories** (per broad slot; the server rejects anything else):
top: `t_shirt, shirt, blouse, polo, tank_top, vest, sweater, cardigan, hoodie, sweatshirt, other_top`, one-piece: `dress, jumpsuit, romper`; bottom: `jeans, trousers, chinos, skirt, shorts, leggings, joggers, tights, thermal_leggings, other_bottom`; shoes: `sneakers, boots, loafers, derbies, heels, flats, sandals, other_shoes`; outerwear: `denim_jacket, bomber_jacket, blazer, trench_coat, coat, puffer_jacket, rain_jacket, other_outerwear`; accessory: `belt, scarf, hat, cap, beanie, watch, bag, jewellery, other_accessory`.

### Photos

| Method | Path | Notes |
|---|---|---|
| GET | `/api/items/{id}/photo` | Image bytes (`404` if none). |
| POST | `/api/items/{id}/photo` | Body `{photo_token}` → `201` `Item`. Replaces any existing photo. |
| DELETE | `/api/items/{id}/photo` | `204`. |
| POST | `/api/classify` | multipart `photo` file → `{items: [DraftItem, …]}` (1–8 items; see below). Blocking, ~20–30 s. Each item carries its own `photo_token` (the same photo, copied server-side per draft). |
| POST | `/api/classify/async` | Same upload → `202` job; the job result is a **list** of per-draft `BulkClassifyResultItem` rows: `{ok: true, filename, draft}` / `{ok: false, filename, error}`. |
| POST | `/api/classify/bulk` | multipart **`photos`** (repeated field), up to 20 files → `202` job. Photos are classified **one at a time** (a queue, not a burst). Job `progress: {done, total}` counts **files**; the terminal `result` rows are **per-draft**: a photo that yields k items → k `{ok: true, filename, draft}` rows (same `filename` on each, one `draft` per item — up to 8 per photo); a failed photo → one `{ok: false, filename, error}` row. One bad photo never fails the job. Any invalid file (bad ext/empty/oversize) or >20 files → `422` before the job starts. **Clients with more than 20 photos must chunk them into ≤20-file requests** (jobs still run sequentially server-side); the web frontend does this automatically. |
| POST | `/api/items/from-photo` | **Quick add** — multipart `photo` + optional `persona_id` form field → `201` `{items: [Item, …]}`: **every item detected in the photo is saved** (a flat-lay can add several items in one call; a single-item photo returns a one-element list). The no-review path; drafts with values that can't make a valid item → `503`, nothing saved. |
| GET | `/api/classify/photo/{token}` | The draft photo bytes (for the review form). Each item's token resolves to its own copy. |

`DraftItem` = `{name, category, type, color, warmth, formality, style_tags, photo_token}` —
the vision model's suggestion; the user reviews before saving (misjudged
warmth/formality would skew every later recommendation). `category` is the
detailed classification; `type` is the broad slot the backend derives from it
(a claimed type that disagrees with the category is rejected, never saved).
**One photo may return several items** — a flat-lay with several clothes in it becomes
one `DraftItem` per piece (up to 8; the backend truncates beyond that);
single-item photos return exactly one. Each item has its own `photo_token`
(the same photo copied per draft, so every draft can be saved as its own
item). Quick add (`/api/items/from-photo`) skips that review by design —
trust the model, and every detected item is saved.

### Recommendation

| Method | Path | Notes |
|---|---|---|
| POST | `/api/outfits/recommend` | Body `{mood, occasion, activity?, weather_override_c?, persona_ids?, count?}` → `RecommendResponse`. Blocking. `activity` (free text, ≤200 chars) is what the person will actually be doing ("Christmas dinner", "zoo day", "wedding") — it steers the stylist and guarantees a warm-layer option (cardigan) in the candidate pool; `count` (1–5, default 1) asks for several outfit **options** per persona — each differs from the ones before it; use `/async` for `count > 1` (several sequential model calls). |
| POST | `/api/outfits/recommend/async` | Same body → `202` job; result is a `RecommendResponse`. Recommended whenever `count > 1`. |

`RecommendResponse` = `{title, outfit: [{slot, item}], rationale, source: "llm"\|"fallback", gaps: [..], weather, history_id, outfits: [PersonaOutfit]}` — `outfits` carries one entry per (persona, option): `PersonaOutfit` = `{persona_id, persona_name, title, outfit, rationale, source, gaps, history_id, option}` where `option` is the 1-based position among that persona's options. An outfit is role-consistent: exactly one primary top (or a one-piece, which replaces top and bottom), at most one layer piece (cardigan) over it, exactly one primary bottom (or none with a one-piece), at most one underlayer (tights/leggings) under a skirt/dress/shorts outfit, exactly one shoes item — so `outfit` can hold two entries with slot `top` (top + cardigan) or `bottom` (skirt + tights). Recommendations never fail for soft problems (weather down, model down): they
degrade and tell you why in `gaps`.

**Variety:** re-asking with the same prompt will not repeat the same outfit. Every stylist call is shown the persona's recently suggested outfits (last 3 history entries plus earlier options in the same request) with a rule to vary; the deterministic fallback rotates away from those items while a slot has alternatives. `times_worn` is untouched by merely suggesting.

### Jobs

| Method | Path | Notes |
|---|---|---|
| GET | `/api/jobs/{id}` | `{job_id, status: queued\|running\|done\|failed, result?, error?, progress?}`. `progress` (`{done, total}`) is reported by bulk classify jobs; `null` for others. Finished jobs are kept ~1 h. |

### History & worn tracking

| Method | Path | Notes |
|---|---|---|
| GET | `/api/history` | `?limit=` (1–100). Entries: `{id, created_at, mood, occasion, weather, items, rationale, source, worn_at}`. |
| GET | `/api/history/{id}` | One entry. |
| POST | `/api/history/{id}/worn` | "I wore this" — stamps `worn_at`, increments each item's `times_worn` once. Idempotent → `{history_id, already_worn, item_ids}`. |

### Personas (multi-persona wardrobes)

The app can dress several people (e.g. a couple), each with their own wardrobe.
Persona selection is **optional everywhere**: absent parameters mean the first
persona, so pre-persona clients keep working unchanged.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/personas` | `[{id, name, description?, gender}]`, ordered by creation. `description` is free-text styling notes for the LLM (e.g. "no hats — they don't suit me"). `gender` is `male`, `female` or `unspecified`. |
| POST | `/api/personas` | `{name, description?, gender?}` → `201 {id, name, description, gender}`. Absent/null `gender` stores `unspecified`. |
| PUT | `/api/personas/{id}` | `{name?, description?, gender?}` — merge semantics: absent key keeps its value; `description: null`/`""` clears it; `gender: null` resets to `unspecified`. The description and gender steer the stylist LLM (they appear in the prompt as notes the model must respect); they do not affect the deterministic fallback. |
| DELETE | `/api/personas/{id}` | `204`. **400** if last persona; **409** if their wardrobe still has items (move/delete them first). |

- `GET /api/items?persona_id=2` — list that person's wardrobe (absent = first persona). `Item.persona_id` says whose it is.
- `POST /api/items` accepts `persona_id`; `PUT /api/items/{id}` with `persona_id` moves the item to another wardrobe (absent = keep).
- `POST /api/outfits/recommend` (and `/async`) accepts **`persona_ids: [1, 2]`**. With one id: exactly as before. With several: **paired mode** — one outfit per person, sequenced so each stylist call after the first is told what the others wear (coordinated colors/dressiness, no repeated statement pieces). One weather fetch is shared.
  - Response adds **`outfits: [{persona_id, persona_name, title, outfit, rationale, source, gaps, history_id}]`** — one entry per person, each logged to that person's history. Top-level `title/outfit/rationale/history_id/source/gaps` mirror the **first** persona for backward compatibility.
- `GET /api/history?persona_id=2` — filter one person's outfit history (absent = everyone's).

## Settings & weather

| Method | Path | Notes |
|---|---|---|
| GET | `/api/settings` | `{city, model, ollama_url, vision_model}` (effective values). |
| PUT | `/api/settings` | **Absent key = keep current; null/empty = reset to default.** |
| GET | `/api/weather` | Current weather for the settings city (`503` if unreachable). |

### App install (easy download)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/app/download` | `{primary_url, lan_urls, qr_svg_url, manifest_url, install_hint}` — where a phone should point. |
| GET | `/api/app/qr.svg` | QR code encoding the LAN URL; scan with a phone camera to load the app. |
| GET | `/api/health` | Liveness: `{status, version}`. |

## Installable app (PWA)

The frontend is a PWA: `manifest.webmanifest` + service worker + icons. On a
phone, open the LAN URL, then "Add to Home Screen" (iOS) or "Install app"
(Android) — it behaves like a native app, fullscreen, with its own icon. The
install page (`/install.html`) shows the QR code and platform instructions.
`GET /api/app/download` gives a mobile client the same info programmatically.

## Minimal mobile client sketch

```js
const API = "http://192.168.1.20:8000";

// Ask for an outfit without holding a long connection:
async function recommend(mood, occasion) {
  const { job_id } = await fetch(`${API}/api/outfits/recommend/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mood, occasion }),
  }).then((r) => r.json());

  for (;;) {
    const job = await fetch(`${API}/api/jobs/${job_id}`).then((r) => r.json());
    if (job.status === "done") return job.result;
    if (job.status === "failed") throw new Error(job.error);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

// Ask for a coordinated pair (both wardrobes, one request):
async function recommendPair(mood, personaIds) {
  const { job_id } = await fetch(`${API}/api/outfits/recommend/async`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mood, persona_ids: personaIds }),
  }).then((r) => r.json());

  for (;;) {
    const job = await fetch(`${API}/api/jobs/${job_id}`).then((r) => r.json());
    if (job.status === "done") return job.result; // result.outfits = one per person
    if (job.status === "failed") throw new Error(job.error);
    await new Promise((r) => setTimeout(r, 1500));
  }
}

// Add items from a photo (a flat-lay may yield several drafts):
async function addItemFromPhoto(file) {
  const fd = new FormData();
  fd.append("photo", file);
  const { items } = await fetch(`${API}/api/classify`, { method: "POST", body: fd })
    .then((r) => r.json());          // items[i].warmth etc. for the user to review
  return Promise.all(items.map((draft) =>
    fetch(`${API}/api/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...draft, photo_token: draft.photo_token }),
    }).then((r) => r.json())
  ));
}
```
