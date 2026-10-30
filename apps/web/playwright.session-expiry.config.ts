import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.TC_SESSION_BASE_URL || 'http://127.0.0.1:13048'
const target = new URL(baseURL)
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost'].includes(target.hostname) ||
  target.username ||
  target.password
)
  throw new Error('Session expiry acceptance requires a local HTTP test server')

// Only the owning pytest harness supplies the real persisted principals/services.
export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'session-expiry.acceptance.ts',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }], ['json']],
  outputDir: 'test-results/session-expiry/browser',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    extraHTTPHeaders: {
      Origin: baseURL,
      Referer: `${baseURL}/dashboard/security`,
    },
    storageState: { cookies: [], origins: [] },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
