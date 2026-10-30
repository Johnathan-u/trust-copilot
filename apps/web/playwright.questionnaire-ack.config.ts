import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.TC_QNR_ACK_BASE_URL || 'http://127.0.0.1:13421'
const target = new URL(baseURL)
if (
  target.protocol !== 'http:' ||
  !['127.0.0.1', 'localhost'].includes(target.hostname) ||
  target.username ||
  target.password
)
  throw new Error(
    'Questionnaire acknowledgement acceptance requires a local HTTP test server'
  )

// The owning pytest harness supplies real users and manages both local services.
// Deliberately not a generic *.spec.ts test: never run without those fixtures.
export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'questionnaire-ack.acceptance.ts',
  timeout: 180_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [['list'], ['html', { open: 'never' }], ['json']],
  outputDir: 'test-results/questionnaire-ack/browser',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    extraHTTPHeaders: {
      Origin: baseURL,
      Referer: `${baseURL}/dashboard/questionnaires`,
    },
    storageState: { cookies: [], origins: [] },
    // No trace/video containing authentication cookies or password submissions.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
