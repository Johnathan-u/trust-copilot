/**
 * Reproduce questionnaire "Generate answers" freeze.
 * Run with stack up: BASE_URL=http://localhost:3000 node scripts/repro-questionnaire-freeze.js
 * Logs: console errors, network requests after click, whether UI is stuck.
 */
const { chromium } = require('playwright');
const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const consoleLogs = [];
  const networkRequests = [];
  const networkResponses = [];

  page.on('console', (msg) => {
    const t = msg.type();
    const text = msg.text();
    consoleLogs.push({ type: t, text: text.slice(0, 500) });
    if (t === 'error') console.error('CONSOLE ERROR:', text);
  });

  page.on('request', (req) => {
    const url = req.url();
    if (url.includes('/api/')) networkRequests.push({ url: url.slice(-80), method: req.method() });
  });
  page.on('response', (res) => {
    const url = res.url();
    if (url.includes('/api/')) networkResponses.push({ url: url.slice(-80), status: res.status() });
  });

  try {
    await page.goto(BASE_URL + '/login', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.fill('input[type="email"]', 'demo@trust.local');
    await page.fill('input[type="password"]', 'j');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null),
      page.click('button[type="submit"]'),
    ]);
    if (!page.url().includes('/dashboard')) {
      console.log('Login failed, url:', page.url());
      await browser.close();
      return;
    }

    const reviewId = process.env.REVIEW_ID || '1';
    console.log('Navigating to review/', reviewId);
    await page.goto(BASE_URL + '/dashboard/review/' + reviewId, { waitUntil: 'networkidle', timeout: 20000 });

    const genBtn = page.getByRole('button', { name: /Generate answers/ }).first();
    const count = await genBtn.count();
    if (count === 0) {
      console.log('Generate answers button not found. CanExport may be false or page still loading.');
      const body = await page.locator('body').textContent();
      console.log('Body contains "Generating":', body?.includes('Generating'));
      console.log('Body contains "Questionnaires":', body?.includes('Questionnaires'));
    } else {
      console.log('Clicking Generate answers...');
      networkRequests.length = 0;
      networkResponses.length = 0;
      consoleLogs.length = 0;
      await genBtn.click();

      await page.waitForTimeout(15000);

      const generatingVisible = await page.getByText('Generating…').isVisible().catch(() => false);
      const stillHasButton = await page.getByRole('button', { name: 'Generate answers' }).first().isVisible().catch(() => false);
      console.log('After 15s - "Generating…" visible:', generatingVisible, '| "Generate answers" button visible:', stillHasButton);
      console.log('Network requests after click:', networkRequests.length);
      networkRequests.forEach((r) => console.log('  ', r.method, r.url));
      console.log('Network responses:', networkResponses.length);
      networkResponses.forEach((r) => console.log('  ', r.status, r.url));
      console.log('Console errors:', consoleLogs.filter((l) => l.type === 'error').length);
      consoleLogs.filter((l) => l.type === 'error').forEach((l) => console.log('  ', l.text));
    }

    await browser.close();
  } catch (e) {
    console.error('Repro error:', e.message);
    await browser.close();
  }
}

run();
