// The Ask page with Ollama DOWN: the app must degrade to the deterministic
// fallback stylist (source "fallback") and still dress a complete wardrobe,
// with a clear note about the model being unavailable.
import { expect, test } from "@playwright/test";
import {
  getItems,
  getHistory,
  resetPersonaWorld,
  seedExclusiveWardrobe,
  uniqueName,
} from "./helpers";

test.beforeEach(async ({ request }) => {
  // Own our isolation: drop personas and wardrobe rows left by earlier
  // spec files, so "Me" is the first persona (this spec asserts on the
  // default persona's card) regardless of run order or --repeat-each.
  await resetPersonaWorld(request);
  // A wearable wardrobe at 15°C casual: top + bottom + shoes (warmth 2).
  // Exclusive: wipe the default wardrobe first so this spec's seed is
  // the only candidate set (fallback tie-breaks by lower id).
  const { persona, items } = await seedExclusiveWardrobe(
    request,
    uniqueName("fallback")
  );
  expect(persona.id).toBeGreaterThan(0);
  expect(items.length).toBe(5);
});

test("mood submit with Ollama down yields a complete fallback outfit", async ({
  page,
  request,
}) => {
  await page.goto("/index.html");

  await page.fill("#mood", "cosy and unhurried, something soft");
  await page.selectOption("#occasion", "casual");
  await page.click("#ask-btn");

  // The result card appears with one persona-outfit card.
  await expect(page.locator("#result")).toBeVisible();
  await expect(page.locator("#status")).toHaveText("");
  const card = page.locator(".persona-outfit").first();
  await expect(card).toBeVisible();

  // The default persona's card is headed by their name (h3).
  await expect(card.locator("h3")).toHaveText("Me");

  // Complete outfit (the seeded wardrobe covers every required slot at
  // 15°C casual): the required pieces are present, labelled by their
  // DETAILED CATEGORY (the display value), not the broad slot.
  const pieces = card.locator(".outfit-piece");
  await expect(pieces.first()).toBeVisible();
  expect(await pieces.count()).toBeGreaterThanOrEqual(3);
  const slots = await pieces.locator(".slot").allTextContents();
  for (const required of ["T-shirt", "Jeans", "Sneakers"]) {
    expect(slots).toContain(required);
  }

  // The fallback safe-pick note: the deterministic rationale text (and
  // the gaps list carries the "start Ollama" note the UI appends for
  // fallback source). Either place proves the fallback path ran.
  const gapsText = await card.locator(".gaps").innerText();
  const rationaleText = await card.locator(".rationale").innerText();
  expect(gapsText + " " + rationaleText).toMatch(/safe|unavailable|model/i);

  // Pieces come from the real wardrobe (verified via API) — with the
  // exclusive seed they are exactly the items this spec seeded.
  const wardrobe = (await getItems(request)).map((i) => i.name);
  expect(wardrobe.length).toBe(5);
  const shownNames = await pieces.locator(".name").allTextContents();
  for (const shown of shownNames) {
    const bare = shown.replace(/\s*\([^)]*\)\s*$/, ""); // strip " (color)"
    expect(wardrobe).toContain(bare);
  }

  // The recommendation was logged to history with source fallback.
  const [entry] = await getHistory(request);
  expect(entry.source).toBe("fallback");
  expect(entry.items.length).toBeGreaterThanOrEqual(3);

  // Weather degrades too: no live weather in the test env, so the note
  // explains the manual option (never an unhandled error).
  await expect(page.locator("#weather-note")).toContainText(/weather/i);

  // The wear-it button is offered inside the outfit card (per-outfit
  // worn tracking) once a history entry exists.
  const wornBtn = card.locator(".worn-btn");
  await expect(wornBtn).toBeVisible();
  await expect(wornBtn).toHaveText("We wore this today");
});

test("submitting with an empty mood does nothing (client-side guard)", async ({
  page,
}) => {
  await page.goto("/index.html");
  await page.click("#ask-btn");
  // No recommendation request happens; the form stays put.
  await expect(page.locator("#result")).toBeHidden();
  await expect(page.locator("#ask-btn")).toBeEnabled();
});

test("a stated activity ('Christmas dinner') adds a warm layer to the fallback outfit", async ({
  page,
  request,
}) => {
  await resetPersonaWorld(request);
  await seedExclusiveWardrobe(request, uniqueName("activity"));

  await page.goto("/index.html");
  await page.fill("#mood", "festive and warm");
  // What they'll be doing: the engine guarantees a warm-layer option and
  // the deterministic fallback wears it — the cardigan (a top-slot layer,
  // out of the mild-day warmth band without the activity).
  await page.fill("#activity", "Christmas dinner");
  await page.selectOption("#occasion", "casual");
  await page.click("#ask-btn");

  const card = page.locator(".persona-outfit").first();
  await expect(card).toBeVisible();
  const slots = await card.locator(".outfit-piece .slot").allTextContents();
  expect(slots).toContain("Cardigan");
  // The rest of the outfit is still complete.
  expect(slots).toContain("Jeans");
  expect(slots).toContain("Sneakers");
});
