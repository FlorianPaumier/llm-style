// Settings page: city save round-trips as the placeholder (value-as-placeholder
// design), personas can be added from the People card, and deleting a persona
// that still owns items surfaces the API's 409 error in #person-error.
import { expect, test } from "@playwright/test";
import { firstPersona, getItems, postItem, uniqueName } from "./helpers";

test("saving a city round-trips it as the placeholder after reload", async ({
  page,
  request,
}) => {
  const city = uniqueName("Lisbon");
  await page.goto("/settings.html");

  await page.fill("#city", city);
  await page.click("#settings-form button[type=submit]");
  await expect(page.locator("#status")).toHaveText("Saved.");

  // The input clears (empty = "keep this") and the placeholder now shows
  // the effective city.
  await expect(page.locator("#city")).toHaveValue("");
  await expect(page.locator("#city")).toHaveAttribute("placeholder", city);

  // Round-trip through the API too: GET /api/settings reports it.
  const res = await request.get("/api/settings");
  expect(await res.json()).toMatchObject({ city });

  // Reload: the placeholder persists (it comes from the server).
  await page.reload();
  await expect(page.locator("#city")).toHaveAttribute("placeholder", city);
});

test("adding a person via the People form lists them", async ({ page, request }) => {
  const person = uniqueName("Zoe");
  await page.goto("/settings.html");

  await page.fill("#person-name", person);
  await page.click("#person-form button[type=submit]");

  const li = page.locator("#people-list li", { hasText: person });
  await expect(li).toHaveCount(1);
  await expect(page.locator("#person-error")).toHaveText("");

  // The new person really exists server-side.
  const res = await request.get("/api/personas");
  const names = ((await res.json()) as { name: string }[]).map((p) => p.name);
  expect(names).toContain(person);

  // People created by other tests may exist too; ours is listed once.
  await expect(li).toHaveCount(1);
});

test("persona gender round-trips through the People list and reaches the API", async ({
  page,
  request,
}) => {
  const person = uniqueName("Robin");
  await page.goto("/settings.html");

  // Add with a gender chosen straight in the form.
  await page.fill("#person-name", person);
  await page.selectOption("#person-gender", "female");
  await page.click("#person-form button[type=submit]");

  const li = page.locator("#people-list li", { hasText: person });
  await expect(li).toHaveCount(1);
  await expect(page.locator("#person-error")).toHaveText("");
  // The name shows the gender marker; the row select reflects the value.
  await expect(li.locator("span").first()).toHaveText(`♀ ${person}`);
  await expect(li.locator("select.person-gender")).toHaveValue("female");

  // Change it in the row: PUT lands server-side and survives a reload.
  await li.locator("select.person-gender").selectOption("male");
  await expect(li.locator("select.person-gender")).toHaveValue("male");

  const stored = await request.get("/api/personas");
  const robin = ((await stored.json()) as { name: string; gender: string }[]).find(
    (p) => p.name === person
  );
  expect(robin?.gender).toBe("male");

  await page.reload();
  const liAfter = page.locator("#people-list li", { hasText: person });
  await expect(liAfter.locator("span").first()).toHaveText(`♂ ${person}`);
});

test("deleting a persona that still owns items shows the 409 error", async ({
  page,
  request,
}) => {
  const name = uniqueName("Owner");
  const res = await request.post("/api/personas", { data: { name } });
  const persona = (await res.json()) as { id: number; name: string };
  await postItem(request, {
    name: uniqueName("owned shirt"),
    category: "t_shirt",
    type: "top",
    persona_id: persona.id,
  });
  // Sanity: they own exactly one item.
  expect((await getItems(request, persona.id)).length).toBe(1);

  await page.goto("/settings.html");
  const li = page.locator("#people-list li", { hasText: name });

  // Accept the confirm, expect the API's 409 detail in #person-error.
  page.once("dialog", (dialog) => dialog.accept());
  await li.getByRole("button", { name: "Delete" }).click();

  await expect(page.locator("#person-error")).toContainText(/still has 1 item/i);
  // The persona is still listed — deletion was refused.
  await expect(li).toHaveCount(1);

  // The default persona ("Me") is refused too — but ONLY while they own
  // items: the API protects the last persona and non-empty wardrobes,
  // not the default persona per se. Give Me an item first, or this step
  // would REALLY delete them and every later spec that assumes "Me"
  // exists (ask-fallback's first card, firstPersona() seeding) breaks.
  const me = await firstPersona(request);
  await postItem(request, {
    name: uniqueName("me shirt"),
    category: "t_shirt",
    type: "top",
    persona_id: me.id,
  });
  const meLi = page
    .locator("#people-list li")
    .filter({ has: page.locator("span", { hasText: new RegExp(`^${me.name}$`) }) });
  page.once("dialog", (dialog) => dialog.accept());
  await meLi.getByRole("button", { name: "Delete" }).click();
  // A fresh 409 lands in #person-error and Me stays listed.
  await expect(page.locator("#person-error")).toContainText(/still has/i);
  await expect(meLi).toHaveCount(1);
  // ... and really survives server-side (the UI list alone is not proof).
  const after = await request.get("/api/personas");
  const idsAfter = ((await after.json()) as { id: number }[]).map((p) => p.id);
  expect(idsAfter).toContain(me.id);
});
