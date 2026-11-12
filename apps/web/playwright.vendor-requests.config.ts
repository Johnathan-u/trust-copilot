import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.TC_VENDOR_BASE_URL || 'http://127.0.0.1:13042'
const target = new URL(baseURL)
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost'].includes(target.hostname) ||
  target.username ||
  target.password
) {
  throw new Error('Vendor request acceptance requires a local HTTP test server')
}

// The PostgreSQL test owns both services. This filename is not the generic
// browser config, so the release suite does not start it without its database.
export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'vendor-requests.acceptance.ts',
  timeout: 240_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }], ['json']],
  outputDir: `test-results/vendor-requests-restart/browser-${process.env.TC_VENDOR_PHASE || 'discovery'}`,
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    extraHTTPHeaders: {
      Origin: baseURL,
      Referer: `${baseURL}/dashboard/requests`,
    },
    storageState: { cookies: [], origins: [] },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
