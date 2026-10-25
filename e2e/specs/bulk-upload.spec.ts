// Bulk photo upload queue on /wardrobe.html.
//
// The suite's server has Ollama DOWN: classification per photo fails fast
// (connection refused -> ClassificationError), which for the BULK queue
// means the JOB still succeeds — each photo becomes an ok:false row with
// the vision-model-unavailable error, shown inline per queue row.
// The single-file flow is also verified: it keeps the classic
// synchronous /api/classify path and shows the 503 message in the form.
import { expect, test } from "@playwright/test";

// Minimal PNG bytes: the backend never decodes the file, but the
// extension must be allowed (.png) and the upload non-empty.
const PNG = Buffer.from(
  "89504e470d0a1a0a0000000d4948445200000001000000010806000000" +
    "1f15c4890000000a49444154789c6300010000050001od0a2db4" +
    "0000000049454e44ae426082",
  "hex"
);

test.beforeEach(async ({ page }) => {
  await page.goto("/wardrobe.html");
});

test("selecting multiple photos shows the queue, then per-row failures when the vision model is down", async ({ page }) => {
  await page.setInputFiles("#photo-input", [
    { name: "tee.png", mimeType: "image/png", buffer: PNG },
    { name: "jacket.png", mimeType: "image/png", buffer: PNG },
  ]);

  // The queue card appears with one row per file, named after each file.
  const queue = page.locator("#bulk-queue");
  await expect(queue).toBeVisible();
  const rows = queue.locator("#bulk-rows li");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0).locator(".bulk-name")).toHaveText("tee.png");
  await expect(rows.nth(1).locator(".bulk-name")).toHaveText("jacket.png");

  // Ollama is down, so each row fails fast; the job itself still finishes
  // (per-photo failures are caught) and every row shows Failed + the
  // vision-model-unavailable reason inline.
  for (const row of [rows.nth(0), rows.nth(1)]) {
    await expect(row.locator(".bulk-chip")).toHaveText("Failed", { timeout: 20_000 });
    await expect(row.locator(".bulk-error")).toContainText("Vision model unavailable");
  }

  // The queue summary reports both photos processed.
  await expect(page.locator("#bulk-summary")).toHaveText("Classified 2 of 2");
  // No usable Review buttons for failed rows (they stay hidden in the DOM).
  await expect(rows.nth(0).locator("button", { hasText: "Review" })).toBeHidden();
  await expect(rows.nth(1).locator("button", { hasText: "Review" })).toBeHidden();
});

test("a single photo keeps the classic flow: classify fails with the model-down message in the form", async ({ page }) => {
  // One file must NOT open the queue — it goes through the synchronous
  // /api/classify call, whose 503 lands in the form error area.
  await page.setInputFiles("#photo-input", [
    { name: "solo.png", mimeType: "image/png", buffer: PNG },
  ]);

  await expect(page.locator("#bulk-queue")).toBeHidden();
  await expect(page.locator("#photo-preview")).toBeVisible();
  await expect(page.locator("#form-error")).toContainText(
    "Classification failed: Vision model unavailable",
    { timeout: 20_000 }
  );
});

test("Clear hides a finished queue; a new queue can be started afterwards", async ({ page }) => {
  await page.setInputFiles("#photo-input", [
    { name: "one.png", mimeType: "image/png", buffer: PNG },
    { name: "two.png", mimeType: "image/png", buffer: PNG },
  ]);
  const rows = page.locator("#bulk-rows li");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1).locator(".bulk-chip")).toHaveText("Failed", { timeout: 20_000 });

  await page.click("#bulk-clear");
  await expect(page.locator("#bulk-queue")).toBeHidden();

  // After clearing, a fresh multi-file selection starts a new queue.
  await page.setInputFiles("#photo-input", [
    { name: "three.png", mimeType: "image/png", buffer: PNG },
    { name: "four.png", mimeType: "image/png", buffer: PNG },
  ]);
  const rows2 = page.locator("#bulk-rows li");
  await expect(rows2).toHaveCount(2);
  await expect(rows2.nth(0).locator(".bulk-name")).toHaveText("three.png");
});

test("more than 20 photos split into sequential batches — no 422, one row per photo", async ({ page }) => {
  // The backend rejects >20 photos per /api/classify/bulk request, so 21
  // files must be sent as two batches (20 + 1). Proof the split happened:
  // every row fails with the model-down error (a single 21-file POST would
  // have 422'd with "Too many photos" on every row instead), and the queue
  // ends with EXACTLY 21 rows — one per photo, no phantom duplicates.
  const files = Array.from({ length: 21 }, (_, i) => ({
    name: `p${String(i).padStart(2, "0")}.png`,
    mimeType: "image/png",
    buffer: PNG,
  }));
  await page.setInputFiles("#photo-input", files);

  const rows = page.locator("#bulk-rows li");
  await expect(rows).toHaveCount(21);

  // Every photo fails fast (Ollama down) — both batches, sequentially.
  for (let i = 0; i < 21; i++) {
    await expect(rows.nth(i).locator(".bulk-chip")).toHaveText("Failed", { timeout: 20_000 });
    await expect(rows.nth(i).locator(".bulk-error")).toContainText("Vision model unavailable");
  }

  // The summary covers all 21 photos across the two batches.
  await expect(page.locator("#bulk-summary")).toHaveText("Classified 21 of 21");

  // The finished queue is still clearable.
  await page.click("#bulk-clear");
  await expect(page.locator("#bulk-queue")).toBeHidden();
});
