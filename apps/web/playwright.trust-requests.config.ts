import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.TC_TRUST_BASE_URL || 'http://127.0.0.1:13039'
const target = new URL(baseURL)
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost'].includes(target.hostname) ||
  target.username ||
  target.password
) {
  throw new Error('Incoming Trust acceptance requires a local HTTP test server')
}
// The PostgreSQL test owns both services. The non-default filename deliberately
// prevents the generic browser suite from running without its owned DB fixtures.
export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'trust-requests.acceptance.ts',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }], ['json']],
  outputDir: `test-results/trust-requests-restart/browser-${process.env.TC_TRUST_PHASE || 'discovery'}`,
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    extraHTTPHeaders: {
      Origin: baseURL,
      Referer: `${baseURL}/dashboard/trust-requests`,
    },
    storageState: { cookies: [], origins: [] },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
