// Shared helpers for the llm-style e2e specs: API seeding + typed API client.
//
// One backend serves the whole run, so tests stay independent by seeding
// with UNIQUE names (a per-run prefix) and only asserting on what they
// created — never on the total state of the server.
import { APIRequestContext, expect } from "@playwright/test";

export interface ItemPayload {
  name: string;
  category: string; // detailed category; the broad type is derived from it
  type: "top" | "bottom" | "shoes" | "outerwear" | "accessory";
  color?: string | null;
  warmth?: number;
  formality?: number;
  style_tags?: string | null;
  notes?: string | null;
  persona_id?: number | null;
}

export interface Item extends ItemPayload {
  id: number;
  times_worn: number;
  persona_id: number;
  has_photo: boolean;
  photo_url: string | null;
}

export interface Persona {
  id: number;
  name: string;
}

export interface HistoryEntry {
  id: number;
  created_at: string;
  mood: string;
  occasion: string;
  items: Item[];
  rationale: string | null;
  source: string | null;
  worn_at: string | null;
  persona_id: number | null;
}

// Unique prefix per worker so concurrent specs never collide on names.
export const RUN = `e2e-${process.pid.toString(36)}-${Date.now().toString(36)}`;
let counter = 0;
export const uniqueName = (label: string) => `${RUN}-${label}-${(counter++).toString(36)}`;

/** POST /api/items (default wardrobe) — returns the created item. */
export async function postItem(
  request: APIRequestContext,
  item: ItemPayload
): Promise<Item> {
  const body: Record<string, unknown> = { warmth: 2, formality: 2, ...item };
  const res = await request.post("/api/items", { data: body });
  expect(res.status()).toBe(201);
  return (await res.json()) as Item;
}

/** POST /api/personas — returns the created persona. */
export async function postPersona(
  request: APIRequestContext,
  name: string
): Promise<Persona> {
  const res = await request.post("/api/personas", { data: { name } });
  expect(res.status()).toBe(201);
  return (await res.json()) as Persona;
}

/**
 * Seed a mini-wardrobe for one persona that the fallback stylist can
 * dress at ~15°C casual: top + bottom + shoes at warmth 2 (band 1-2 at
 * 15°C), formality 2 (casual band 1-3, target 2).
 */
export async function seedWardrobe(
  request: APIRequestContext,
  personaId: number,
  label: string,
  overrides: Partial<ItemPayload>[] = []
): Promise<Item[]> {
  const base: ItemPayload[] = [
    { name: `${label} tee`, category: "t_shirt", type: "top", color: "white", warmth: 2, formality: 2 },
    { name: `${label} jeans`, category: "jeans", type: "bottom", color: "blue", warmth: 2, formality: 2 },
    { name: `${label} sneakers`, category: "sneakers", type: "shoes", color: "white", warmth: 2, formality: 2 },
    // A cardigan is a top-slot layer (role layer_upper): out of the mild-day
    // warmth band at 15°C, so the fallback never layers it unless asked.
    { name: `${label} cardigan`, category: "cardigan", type: "top", color: "grey", warmth: 4, formality: 2 },
    { name: `${label} cap`, category: "cap", type: "accessory", color: "black", warmth: 1, formality: 2 },
  ];
  const items = [...base];
  for (let i = 0; i < overrides.length; i++) {
    items[i] = { ...items[i], ...overrides[i], persona_id: personaId };
  }
  const created: Item[] = [];
  for (const it of items) {
    created.push(await postItem(request, { ...it, persona_id: personaId }));
  }
  return created;
}

/**
 * Seed a wardrobe for the DEFAULT persona whose items are guaranteed to
 * be the fallback pick, regardless of leftovers from earlier specs.
 *
 * The deterministic fallback stylist picks per slot the candidate with
 * formality closest to the occasion target (casual -> 2), breaking ties
 * by LOWER id — so older identical items always win. Wiping the default
 * wardrobe first makes the spec's items the only candidates, so the pick
 * is unambiguous.
 */
export async function seedExclusiveWardrobe(
  request: APIRequestContext,
  label: string
): Promise<{ persona: Persona; items: Item[] }> {
  const persona = await firstPersona(request);
  await clearDefaultWardrobe(request);
  const items = await seedWardrobe(request, persona.id, label);
  return { persona, items };
}

/**
 * Delete every item in the DEFAULT persona's wardrobe. The deterministic
 * fallback stylist tie-breaks identical candidates by LOWER id, so items
 * left over from earlier specs would always beat a spec's own seed.
 * Wiping first makes "which items get recommended" unambiguous.
 */
export async function clearDefaultWardrobe(
  request: APIRequestContext
): Promise<void> {
  const items = await getItems(request);
  for (const it of items) {
    const res = await request.delete(`/api/items/${it.id}`);
    expect(res.status()).toBe(204);
  }
}

/** GET /api/items filtered to one persona's wardrobe. */
export async function getItems(
  request: APIRequestContext,
  personaId?: number
): Promise<Item[]> {
  const url = personaId
    ? `/api/items?persona_id=${personaId}&page_size=200`
    : "/api/items?page_size=200";
  const res = await request.get(url);
  expect(res.status()).toBe(200);
  return (await res.json()).items as Item[];
}

/** GET /api/history for one persona (or all). */
export async function getHistory(
  request: APIRequestContext,
  personaId?: number
): Promise<HistoryEntry[]> {
  const url = personaId
    ? `/api/history?persona_id=${personaId}`
    : "/api/history?limit=100";
  const res = await request.get(url);
  expect(res.status()).toBe(200);
  return (await res.json()) as HistoryEntry[];
}

/**
 * A fallback (Ollama-down) recommendation over one persona's wardrobe.
 * Uses the API directly — the browser specs drive the same endpoint
 * through the UI. Weather override 15°C keeps the pick deterministic
 * and skips the live-weather network call.
 */
export async function apiRecommend(
  request: APIRequestContext,
  mood: string,
  persona_ids: number[],
  occasion = "casual"
) {
  const res = await request.post("/api/outfits/recommend", {
    data: { mood, occasion, persona_ids, weather_override_c: 15 },
  });
  expect(res.status()).toBe(200);
  return await res.json();
}

/** First (default) persona, named "Me" on a fresh DB. */
export async function firstPersona(request: APIRequestContext): Promise<Persona> {
  const res = await request.get("/api/personas");
  expect(res.status()).toBe(200);
  const personas = (await res.json()) as Persona[];
  expect(personas.length).toBeGreaterThan(0);
  return personas[0];
}

/**
 * Reset the world to "first persona only, empty wardrobe": deletes every
 * item and every persona after the first. For specs that assert absolute
 * counts (#count, persona-chip counts) — they can't tolerate leftovers
 * from previously-run spec files sharing the one test server.
 */
export async function resetPersonaWorld(request: APIRequestContext): Promise<void> {
  // Wipe every persona's wardrobe (not just the default one), then drop
  // every persona after the first.
  const res = await request.get("/api/personas");
  expect(res.status()).toBe(200);
  const personas = (await res.json()) as Persona[];
  for (const p of personas) {
    for (const it of await getItems(request, p.id)) {
      const del = await request.delete(`/api/items/${it.id}`);
      expect(del.status()).toBe(204);
    }
  }
  for (const p of personas.slice(1)) {
    const del = await request.delete(`/api/personas/${p.id}`);
    expect([204, 409]).toContain(del.status());
    if (del.status() === 409) {
      throw new Error(
        `persona ${p.id} still had items after wipe; test isolation broken`
      );
    }
  }
}
