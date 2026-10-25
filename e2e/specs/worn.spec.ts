// "We wore this today": after a recommendation the per-card worn button
// marks that history entry (worn_at set, times_worn incremented) — verified
// through the API, since worn state is backend truth.
//
// With the count feature the button moved into each outfit card: options
// are alternatives, so marking one worn must never touch the others.
import { expect, test } from "@playwright/test";
import { getHistory, seedExclusiveWardrobe, uniqueName } from "./helpers";

test("clicking We wore this today marks the history entry worn", async ({
  page,
  request,
}) => {
  // The fallback stylist tie-breaks by lowest id, so leftovers from
  // earlier specs would win over this spec's seed. Wipe first, then
  // seed: OUR items are then the only candidates.
  const { persona, items: seeded } = await seedExclusiveWardrobe(
    request,
    uniqueName("worn")
  );

  await page.goto("/index.html");
  await page.fill("#mood", "a good day for a walk");
  await page.selectOption("#occasion", "casual");
  await page.click("#ask-btn");

  await expect(page.locator("#result")).toBeVisible();
  const card = page.locator(".persona-outfit").first();
  const wornBtn = card.locator(".worn-btn");
  await expect(wornBtn).toBeVisible();
  await expect(wornBtn).toBeEnabled();
  await expect(card.locator(".worn-status")).toHaveText("");

  // Before: the recommendation created a fresh (not yet worn) entry...
  const before = (await getHistory(request, persona.id))[0];
  expect(before).toBeDefined();
  expect(before.worn_at).toBeNull();
  // ...recommending a complete outfit from OUR seeded wardrobe.
  expect(before.items.length).toBeGreaterThanOrEqual(3);
  const seededIds = new Set(seeded.map((i) => i.id));
  for (const item of before.items) {
    expect(seededIds.has(item.id)).toBe(true);
  }

  await wornBtn.click();

  // The button's confirmation is the sync barrier: it appears only after
  // the server finished BOTH writes (worn_at and times_worn commit in
  // two separate transactions — fetching history in between would race).
  await expect(card.locator(".worn-status")).toHaveText("Noted — wear it well!");

  // After: worn_at is set server-side...
  const after = (await getHistory(request, persona.id))[0];
  expect(after.worn_at).not.toBeNull();
  // ...and every item in the outfit got its counter bumped.
  for (const item of after.items) {
    expect(item.times_worn).toBeGreaterThanOrEqual(1);
  }

  await expect(wornBtn).toBeDisabled();
});
