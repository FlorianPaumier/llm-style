// The "How many options?" select (1/3/5) on the Ask page.
//
// The e2e server has Ollama DOWN, so count>1 exercises the async job
// route + fallback rotation: three options, each a distinct combination
// (the avoid-set rotates away from earlier options while the wardrobe
// has alternatives), each with its own per-card worn button that marks
// only that option's history entry.
import { expect, test } from "@playwright/test";
import { getHistory, postItem, resetPersonaWorld, firstPersona, uniqueName } from "./helpers";

test.beforeEach(async ({ request }) => {
  // Own our isolation: default persona only, empty wardrobe.
  await resetPersonaWorld(request);
});

test("asking for 3 options yields three distinct fallback outfits", async ({
  page,
  request,
}) => {
  // A wardrobe rich enough that every required slot has in-band
  // alternatives for the fallback's avoid-set to rotate through
  // (warmth 2 / formality 2 at the assumed 15°C casual band).
  const persona = await firstPersona(request);
  const label = uniqueName("opt");
  const slots = [
    ["top", "t_shirt", ["tee", "shirt", "blouse"]],
    ["bottom", "jeans", ["jeans", "chinos", "skirt"]],
    ["shoes", "sneakers", ["sneakers", "loafers", "boots"]],
  ] as const;
  for (const [type, category, names] of slots) {
    for (const n of names) {
      await postItem(request, {
        name: `${label} ${n}`,
        category,
        type,
        warmth: 2,
        formality: 2,
        persona_id: persona.id,
      });
    }
  }

  await page.goto("/index.html");
  // Unique mood: the history assertion below scopes by it, so repeated
  // runs (--repeat-each) must never match earlier repetitions' entries.
  const mood = uniqueName("something different");
  await page.fill("#mood", mood);
  await page.selectOption("#occasion", "casual");
  await page.selectOption("#count", "3");
  await page.click("#ask-btn");

  // The async path: job runs, then three cards render.
  const cards = page.locator(".persona-outfit");
  await expect(cards).toHaveCount(3, { timeout: 20_000 });

  // Options 2 and 3 carry their label chips; option 1 doesn't.
  await expect(cards.nth(1).locator(".option-chip")).toHaveText("Option 2");
  await expect(cards.nth(2).locator(".option-chip")).toHaveText("Option 3");
  await expect(cards.nth(0).locator(".option-chip")).toHaveCount(0);

  // Distinct combinations: no two options show the same item set.
  const sets: string[][] = [];
  for (let i = 0; i < 3; i++) {
    const names = await cards.nth(i).locator(".outfit-piece .name").allTextContents();
    expect(names.length).toBeGreaterThanOrEqual(3);
    sets.push(names.map((n) => n.replace(/\s*\(.*\)\s*$/, "").trim()).sort());
  }
  const combos = new Set(sets.map((s) => s.join("|")));
  expect(combos.size).toBe(3);

  // Three history entries were logged for THIS ask (one per option), all
  // fallback. Other specs' history may linger (resetPersonaWorld clears
  // wardrobes, not history) — scope by this test's unique mood text.
  const history = (await getHistory(request, persona.id)).filter(
    (e) => e.mood === mood
  );
  expect(history.length).toBe(3);
  for (const entry of history) {
    expect(entry.source).toBe("fallback");
  }

  // Per-card worn buttons: marking option 1 worn leaves the others fresh.
  await cards.nth(0).locator(".worn-btn").click();
  await expect(cards.nth(0).locator(".worn-status")).toHaveText(
    "Noted — wear it well!"
  );
  const after = (await getHistory(request, persona.id)).filter(
    (e) => e.mood === mood
  );
  const wornEntries = after.filter((entry) => entry.worn_at !== null);
  expect(wornEntries).toHaveLength(1);
});

test("the count select defaults to one and one card renders", async ({ page, request }) => {
  const persona = await firstPersona(request);
  const label = uniqueName("single");
  const singles = [
    ["top", "t_shirt"],
    ["bottom", "jeans"],
    ["shoes", "sneakers"],
  ] as const;
  for (const [type, category] of singles) {
    await postItem(request, {
      name: `${label} ${type}`,
      category,
      type,
      warmth: 2,
      formality: 2,
      persona_id: persona.id,
    });
  }

  await page.goto("/index.html");
  await expect(page.locator("#count")).toHaveValue("1");

  await page.fill("#mood", "just one today");
  await page.click("#ask-btn");

  const cards = page.locator(".persona-outfit");
  await expect(cards).toHaveCount(1, { timeout: 20_000 });
  // No option chips on a single-option request.
  await expect(cards.nth(0).locator(".option-chip")).toHaveCount(0);
  await expect(page.locator("#status")).toHaveText("");
});
