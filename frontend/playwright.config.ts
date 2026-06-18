import { defineConfig, devices } from '@playwright/test'

const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  // In CI: only the smoke test (no backend required).
  // Locally: all specs.
  testMatch: CI ? ['**/smoke.spec.ts'] : ['**/*.spec.ts'],
  fullyParallel: false,
  retries: 1,
  workers: 1,
  reporter: CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: CI ? [] : ['**/mobile.spec.ts'],
    },
    // Mobile project only active locally (excluded by testMatch in CI)
    {
      name: 'mobile',
      use: { ...devices['iPhone 12'], browserName: 'chromium' },
      testMatch: CI ? [] : ['**/mobile.spec.ts'],
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !CI,
    timeout: 30_000,
  },
})
