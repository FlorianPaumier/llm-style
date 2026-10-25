import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './specs-dotnet', fullyParallel: false, workers: 1, timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:8798', headless: true },
  webServer: { command: 'node serve_dotnet.mjs', url: 'http://127.0.0.1:8798/api/health', reuseExistingServer: false, timeout: 60000 },
});
