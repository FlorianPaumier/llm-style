// Pair mode: two personas selected on the Ask page -> two coordinated
// outfit cards, each dressed from THEIR OWN wardrobe.
import { expect, test } from "@playwright/test";
import { firstPersona, getItems, postPersona, seedWardrobe, uniqueName } from "./helpers";

test("two selected personas each get an outfit from their own wardrobe", async ({
  page,
  request,
}) => {
  const label = uniqueName("pair");
  const me = await firstPersona(request);
  const partner = await postPersona(request, uniqueName("Partner"));
  // Distinct mini-wardrobes: every piece name is prefixed per persona.
  const mine = await seedWardrobe(request, me.id, `${label}-me`);
  const theirs = await seedWardrobe(request, partner.id, `${label}-them`);

  await page.goto("/index.html");

  // Select both people (multi-select chips).
  const chips = page.locator("#persona-picker .persona-chip");
  await expect(chips).toHaveCount(2);
  await chips.filter({ hasText: partner.name }).click();
  await expect(chips.filter({ hasText: me.name })).toHaveAttribute("aria-pressed", "true");
  await expect(chips.filter({ hasText: partner.name })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#pair-hint")).toBeVisible();

  await page.fill("#mood", "matching energy, relaxed but put-together");
  await page.selectOption("#occasion", "casual");
  await page.click("#ask-btn");

  // Two cards, one per selected persona, each headed by the persona name.
  const cards = page.locator(".persona-outfit");
  await expect(cards).toHaveCount(2);
  const cardNames = await cards.locator("h3").allTextContents();
  expect(cardNames).toEqual(expect.arrayContaining([me.name, partner.name]));
  expect(new Set(cardNames).size).toBe(2);

  // Each card: a complete outfit (>= 3 pieces) drawn only from that
  // person's wardrobe (names verified against the API).
  const mineNames = new Set((await getItems(request, me.id)).map((i) => i.name));
  const theirNames = new Set((await getItems(request, partner.id)).map((i) => i.name));

  const cardByPersona = async (name: string) =>
    cards.filter({ has: page.locator("h3", { hasText: name }) });

  for (const [name, wardrobeSet, notInSet] of [
    [me.name, mineNames, theirNames],
    [partner.name, theirNames, mineNames],
  ] as const) {
    const card = await cardByPersona(name);
    await expect(card).toHaveCount(1);
    const pieces = card.locator(".outfit-piece");
    expect(await pieces.count()).toBeGreaterThanOrEqual(3);

    const slots = await pieces.locator(".slot").allTextContents();
    // Pieces are labelled by their detailed category (the display value).
    for (const required of ["T-shirt", "Jeans", "Sneakers"]) {
      expect(slots).toContain(required);
    }

    for (const shown of await pieces.locator(".name").allTextContents()) {
      const bare = shown.replace(/\s*\([^)]*\)\s*$/, ""); // strip " (color)"
      expect(wardrobeSet.has(bare), `${name}'s card must show their ${bare}`).toBe(true);
      expect(notInSet.has(bare), `${name}'s card must not show ${bare}`).toBe(false);
    }
  }

  // Pieces seeded per persona really are distinct sets.
  expect(mine.length).toBeGreaterThan(0);
  expect(theirs.length).toBeGreaterThan(0);
});
