import { defineConfig, devices } from '@playwright/test'

const port = process.env.TC_RULES_EVIDENCE_PORT || '13111'
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './e2e/integration',
  testMatch: 'notification-rules-evidence.spec.ts',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    baseURL,
    trace: 'off',
    video: 'off',
  },
  webServer: {
    command: `npm run dev -- -p ${port}`,
    url: `${baseURL}/login`,
    timeout: 180_000,
    reuseExistingServer: false,
    env: {
      ...process.env,
      API_UPSTREAM: 'http://127.0.0.1:9',
      NEXT_DIST_DIR: '.next-rules-evidence',
      NEXT_TELEMETRY_DISABLED: '1',
    },
  },
})
