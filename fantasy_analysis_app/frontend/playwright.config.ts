import { defineConfig, devices } from '@playwright/test'

// E2E tests run against a dev server the operator starts (backend on :8000 with
// fixtures loaded + analytics computed, frontend on :5173). See e2e/README.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:5173',
    // Chromium is pre-provisioned in this environment.
    launchOptions: { executablePath: process.env.PW_CHROMIUM ?? '/opt/pw-browsers/chromium' },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
