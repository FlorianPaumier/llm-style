// Playwright config for the llm-style e2e suite.
//
// The webServer launches e2e/serve_test.py, which points LLM_STYLE_DB /
// LLM_STYLE_IMAGES_DIR / LLM_STYLE_DATA_DIR at /tmp/llm-style-e2e/... so
// the suite NEVER touches the user's real data/llm_style.db or photos.
// Ollama is expected to be down: the app degrades to the deterministic
// fallback stylist, which these tests verify explicitly.
import { defineConfig } from "@playwright/test";
import path from "node:path";

// Paths must be relative to the REPO ROOT (Playwright runs the webServer
// command from this config's directory), not the e2e dir.
const ROOT = path.resolve(__dirname, "..");

const PORT = Number(process.env.E2E_PORT || 8799);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, "backend/.venv/bin/python");

export default defineConfig({
  testDir: "./specs",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // one shared throwaway backend; keep it simple
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    headless: true,
    // The app's pages call confirm()/prompt()/alert(); tests opt in via
    // page.on("dialog") where needed, but never let one hang a run.
    actionTimeout: 10_000,
    navigationTimeout: 10_000,
  },
  webServer: {
    command: `"${PYTHON}" "${path.join(ROOT, "e2e/serve_test.py")}" --port ${PORT} --fresh`,
    cwd: ROOT,
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
