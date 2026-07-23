import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    headless: true,
    actionTimeout: 10000,
  },
  webServer: {
    command: 'pnpm.cmd --dir frontend dev --port 5173',
    port: 5173,
    reuseExistingServer: true,
    timeout: 30000,
  },
});
