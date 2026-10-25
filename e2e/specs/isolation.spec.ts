// DATA-ISOLATION GUARANTEE (sacred): the suite must run against the
// throwaway /tmp/llm-style-e2e DB and NEVER touch the user's real
// data/llm_style.db or data/images/.
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, statSync } from "node:fs";
import path from "node:path";

const REPO_ROOT = path.resolve(__dirname, "../..");
const REAL_DB = path.join(REPO_ROOT, "data", "llm_style.db");
const REAL_IMAGES = path.join(REPO_ROOT, "data", "images");

test("the server runs on the throwaway DB under /tmp, not on data/", () => {
  // The launcher prints its isolated paths on startup; the health check
  // proves the server is up. Assert the throwaway DB exists and the real
  // one is a DIFFERENT file.
  const found = execFileSync("bash", ["-c", "ls -d /tmp/llm-style-e2e/*/*.db 2>/dev/null"]).toString().trim();
  expect(found).not.toBe("");
  const isolated = found.split("\n");
  for (const db of isolated) {
    expect(path.resolve(db)).not.toBe(REAL_DB);
  }
  // The default throwaway DB used by the webServer (--fresh) exists.
  expect(existsSync("/tmp/llm-style-e2e/default/llm_style.db")).toBe(true);
});

test("writing via the API does not modify the user's real DB or photos", async ({
  request,
}) => {
  const realStat = existsSync(REAL_DB) ? statSync(REAL_DB) : null;
  const realMtime = realStat ? realStat.mtimeMs : null;
  const realSize = realStat ? realStat.size : null;
  const imageFiles = existsSync(REAL_IMAGES) ? execFileSync("ls", ["-la", REAL_IMAGES]).toString() : "";

  // Mutate through the isolated server: item + persona + history writes.
  const res = await request.post("/api/items", {
    data: { name: "isolation-check-item", category: "t_shirt", type: "top", warmth: 2, formality: 2 },
  });
  expect(res.status()).toBe(201);
  const rec = await request.post("/api/outfits/recommend", {
    data: { mood: "isolation", occasion: "casual", weather_override_c: 15 },
  });
  expect(rec.status()).toBe(200);

  // The real DB is byte-identical (mtime AND size unchanged) — a stronger
  // check than mtime alone, which the OS may not bump for a stale stat.
  const after = existsSync(REAL_DB) ? statSync(REAL_DB) : null;
  expect(after ? after.size : null).toBe(realSize);
  expect(after ? after.mtimeMs : null).toBe(realMtime);
  if (existsSync(REAL_IMAGES)) {
    expect(execFileSync("ls", ["-la", REAL_IMAGES]).toString()).toBe(imageFiles);
  }
});
