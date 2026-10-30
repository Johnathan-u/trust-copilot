const { defineConfig, devices } = require('/tmp/tc-15-039d-work/snapshot/apps/web/node_modules/@playwright/test');
const phase = process.env.TC_APPROVAL_PHASE || 'baseline';
module.exports = defineConfig({
  testDir: '/tmp/tc-15-039d-work/snapshot/apps/web/e2e',
  testMatch: '**/release/screen-trust-requests.spec.ts',
  workers: 1,
  retries: 0,
  outputDir: '/tmp/tc-15-039d-work/results-' + phase,
  reporter: [['list'], ['json', { outputFile: '/tmp/tc-15-039d-work/reports/' + phase + '.json' }]],
  use: { baseURL: 'http://127.0.0.1:13255', screenshot: 'only-on-failure', trace: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], launchOptions: { executablePath: '/tmp/tc-pr149-pinned-chrome/chrome-headless-shell-linux64/chrome-headless-shell' } } }],
});
