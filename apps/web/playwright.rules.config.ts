import { defineConfig, devices } from '@playwright/test'

// The PostgreSQL acceptance test owns both real service processes. This config
// does not start the generic demo stack or use its saved authentication state.
const baseURL = process.env.TC_RULES_BASE_URL || 'http://127.0.0.1:13016'
const target = new URL(baseURL)
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost'].includes(target.hostname) ||
  target.username ||
  target.password
) {
  throw new Error('Rules acceptance requires a local HTTP test server')
}

export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'notification-rules.spec.ts',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }], ['json']],
  outputDir: `test-results/rules-restart/browser-${process.env.TC_RULES_PHASE || 'discovery'}`,
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    storageState: { cookies: [], origins: [] },
  },
})
