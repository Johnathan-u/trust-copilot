import { defineConfig, devices } from '@playwright/test'

/**
 * E2E tests for Trust Copilot web app.
 *
 * **Full stack (recommended):** from repo root run `npm run test:e2e` — starts Docker DB,
 * API on 18080, Next on 13000 with API_UPSTREAM, seeds demo user, then Playwright.
 *
 * **Local only:** `cd apps/web && npx playwright test` — webServer starts Next; set
 * `API_UPSTREAM=http://127.0.0.1:8000` and run API separately, or login will fail.
 */
const e2eServer = !!process.env.E2E_SERVER_RUNNING
const webPort = process.env.E2E_WEB_PORT || (e2eServer ? '13000' : '3000')
const baseURL = `http://127.0.0.1:${webPort}`
const salesPort = process.env.E2E_SALES_WEB_PORT || '3100'
const salesBaseURL = `http://127.0.0.1:${salesPort}`

// TC-02-001: E2E runs only against a local stack. Refuse a non-local API_UPSTREAM so loading
// this config (listing or running tests) can never proxy test traffic to staging/production.
const LOCAL_UPSTREAM_HOSTS = new Set([
  'localhost',
  '127.0.0.1',
  '[::1]',
  '::1',
  'api',
])
const apiUpstream = process.env.API_UPSTREAM || 'http://127.0.0.1:8000'
const apiUpstreamHost = (() => {
  try {
    return new URL(apiUpstream).hostname
  } catch {
    return ''
  }
})()
if (!LOCAL_UPSTREAM_HOSTS.has(apiUpstreamHost)) {
  throw new Error(
    `Refusing to run E2E: API_UPSTREAM=${apiUpstream} is not a local host (${[...LOCAL_UPSTREAM_HOSTS].join(', ')})`
  )
}

export default defineConfig({
  testDir: './e2e',
  // When using saved storage from setup, run setup before chromium (dependencies).
  // Without E2E_SERVER_RUNNING, skip setup project so it never races with chromium.
  fullyParallel: !e2eServer,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 1,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    ...(e2eServer
      ? [
          {
            name: 'setup',
            testMatch: /auth\.setup\.ts/ as RegExp,
            // Cold Next compile + first /dashboard can exceed default 30s on Windows CI.
            timeout: 120_000,
          },
        ]
      : []),
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        storageState: e2eServer ? 'e2e/.auth/user.json' : undefined,
      },
      dependencies: e2eServer ? ['setup'] : [],
    },
  ],
  webServer: e2eServer
    ? undefined
    : [
        {
          command: `npm run dev -- -p ${webPort}`,
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
          env: {
            ...process.env,
            API_UPSTREAM: apiUpstream,
            NEXT_PUBLIC_SALES_CONTACT: '',
          },
        },
        {
          command: `npm run dev -- -p ${salesPort}`,
          url: salesBaseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
          env: {
            ...process.env,
            API_UPSTREAM: apiUpstream,
            NEXT_DIST_DIR: '.next-e2e-sales',
            NEXT_PUBLIC_SALES_CONTACT: 'owner.contact@example.com',
          },
        },
      ],
})
