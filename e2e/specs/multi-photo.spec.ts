// Multi-item photo UI on /wardrobe.html.
//
// The e2e server has Ollama DOWN, so every vision call fails fast with
// "Vision model unavailable" — the multi-draft SUCCESS path needs a live
// model and is owned by the backend tests. What these specs pin down is
// the UI mechanics around it:
// - the quick-add checkbox toggle no longer throws (regression: the
//   handler used an undeclared variable in strict mode) and the button
//   only appears once a file is staged; clicking it surfaces the 503 in
//   the form error and re-enables the button;
// - a 2-file bulk queue still renders per-FILE rows while running, fails
//   per row with the model-down error, keeps "Save all" hidden (no ready
//   drafts exist) and stays clearable.
import { expect, test } from "@playwright/test";

// Same minimal PNG bytes as bulk-upload.spec.ts: the backend never decodes
// the file, but the extension must be allowed and the upload non-empty.
const PNG = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010806000000" +
    "1f15c4890000000a49444154789c6300010000050001od0a2db4" +
    "0000000049454e44ae426082",
  "hex"
);

test.beforeEach(async ({ page }) => {
  await page.goto("/wardrobe.html");
});

test("quick-add mode toggles without console errors; the button appears only when a file is staged", async ({ page }) => {
  // Regression: the checkbox handler used to reference an undeclared
  // variable (strict mode -> ReferenceError pageerror) on every toggle.
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  // The button starts hidden (no file staged yet).
  await expect(page.locator("#quick-add-btn")).toBeHidden();

  // Toggle on/off a few times — no console error, button still hidden.
  await page.check("#quick-add-mode");
  await page.uncheck("#quick-add-mode");
  await page.check("#quick-add-mode");
  await expect(page.locator("#quick-add-btn")).toBeHidden();
  expect(pageErrors).toEqual([]);

  // Stage one file: the button becomes visible (no model call yet — the
  // photo is only staged).
  await page.setInputFiles("#photo-input", [
    { name: "flatlay.png", mimeType: "image/png", buffer: PNG },
  ]);
  await expect(page.locator("#quick-add-btn")).toBeVisible();
  expect(pageErrors).toEqual([]);

  // Click it: with Ollama down the 503 lands in the form error area and
  // the button is re-enabled (the finally block).
  await page.click("#quick-add-btn");
  await expect(page.locator("#form-error")).toContainText(
    "Quick add failed: Vision model unavailable",
    { timeout: 20_000 }
  );
  await expect(page.locator("#quick-add-btn")).toBeEnabled();
  expect(pageErrors).toEqual([]);
});

test("a multi-file queue keeps Save all hidden while photos fail (no ready drafts)", async ({ page }) => {
  await page.setInputFiles("#photo-input", [
    { name: "tee.png", mimeType: "image/png", buffer: PNG },
    { name: "jacket.png", mimeType: "image/png", buffer: PNG },
  ]);

  // Rows appear immediately — driven by the selected files, not by
  // results — one row per FILE, named after the file.
  const queue = page.locator("#bulk-queue");
  await expect(queue).toBeVisible();
  const rows = queue.locator("#bulk-rows li");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator(".bulk-name")).toHaveText("tee.png");
  await expect(rows.nth(1).locator(".bulk-name")).toHaveText("jacket.png");

  // Save all starts (and stays) hidden: it only shows up once the queue
  // is finished AND has at least one ready draft.
  await expect(page.locator("#bulk-save-all")).toBeHidden();

  // Ollama down: each file fails fast, per row, and the job still ends.
  for (const row of [rows.nth(0), rows.nth(1)]) {
    await expect(row.locator(".bulk-chip")).toHaveText("Failed", { timeout: 20_000 });
    await expect(row.locator(".bulk-error")).toContainText("Vision model unavailable");
  }

  // Still no ready drafts -> Save all remains hidden.
  await expect(page.locator("#bulk-save-all")).toBeHidden();

  // Clear works on the finished queue.
  await page.click("#bulk-clear");
  await expect(queue).toBeHidden();
});
