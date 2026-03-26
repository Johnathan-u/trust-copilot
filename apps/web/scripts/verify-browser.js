/**
 * In-browser verification: visits routes, collects console errors, tests login + dashboard,
 * and (unless SKIP_GENERATE=1) opens a questionnaire review and clicks Generate answers.
 *
 * Run with the full stack up: BASE_URL=http://localhost:3000 node scripts/verify-browser.js
 *
 * Env:
 *   SKIP_GENERATE=1           — skip generate click (routes + login only)
 *   REVIEW_QUESTIONNAIRE_ID=2 — use this review URL instead of first list item
 *   GENERATE_SETTLE_TIMEOUT_MS=240000 — max wait for job to finish or error toast (default 240000)
 *
 * Outputs JSON to stdout and writes verify-browser-results.json + verify-browser-results.md
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';

const ROUTES = [
  '/login',
  '/dashboard',
  '/dashboard/documents',
  '/dashboard/questionnaires',
  '/dashboard/review/1',
  '/dashboard/requests',
  '/dashboard/exports',
  '/dashboard/compliance-gaps',
  '/dashboard/trust-center',
];

/**
 * @param {import('playwright').Page} page
 * @param {string} baseUrl
 */
async function runGenerateAnswersFlow(page, baseUrl) {
  const flow = {
    skipped: false,
    reason: '',
    questionnaireId: null,
    generatingSeen: false,
    settled: false,
    error: null,
  };

  if (process.env.SKIP_GENERATE === '1') {
    flow.skipped = true;
    flow.reason = 'SKIP_GENERATE=1';
    return flow;
  }

  const envId = process.env.REVIEW_QUESTIONNAIRE_ID;
  let qid = envId && /^\d+$/.test(String(envId).trim()) ? String(envId).trim() : null;

  if (!qid) {
    await page
      .goto(baseUrl + '/dashboard/questionnaires', { waitUntil: 'domcontentloaded', timeout: 20000 })
      .catch(() => null);
    await page.waitForTimeout(2000);
    const links = page.locator('a[href*="/dashboard/questionnaires/"]');
    const n = await links.count();
    for (let i = 0; i < n; i++) {
      const href = await links.nth(i).getAttribute('href');
      const m = href && href.match(/\/dashboard\/questionnaires\/(\d+)/);
      if (m) {
        qid = m[1];
        break;
      }
    }
  }

  if (!qid) {
    flow.skipped = true;
    flow.reason = 'No questionnaire id (empty list or set REVIEW_QUESTIONNAIRE_ID)';
    return flow;
  }

  flow.questionnaireId = qid;
  const reviewUrl = `${baseUrl}/dashboard/review/${qid}`;
  const res = await page.goto(reviewUrl, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch((e) => {
    flow.error = e.message;
    return null;
  });
  if (!res) {
    return flow;
  }
  if (!res.ok()) {
    flow.error = `GET review returned ${res.status()}`;
    return flow;
  }

  await page.waitForTimeout(800);
  const failedLoad = await page.getByText('Failed to load questionnaire').isVisible().catch(() => false);
  if (failedLoad) {
    flow.skipped = true;
    flow.reason = 'Review page: failed to load questionnaire';
    return flow;
  }

  const genBtn = page.getByRole('button', { name: 'Generate answers' }).first();
  const hasGen = await genBtn.isVisible({ timeout: 25000 }).catch(() => false);
  if (!hasGen) {
    flow.skipped = true;
    flow.reason = 'No Generate answers button (missing export permission or different UI)';
    return flow;
  }

  await genBtn.click();

  const generating = page.locator('button').filter({ hasText: /Generating/ }).first();
  flow.generatingSeen = await generating
    .waitFor({ state: 'visible', timeout: 12000 })
    .then(() => true)
    .catch(() => false);

  if (!flow.generatingSeen) {
    flow.error = 'Generating state did not appear within 12s after click';
    return flow;
  }

  const settleMs = Number(process.env.GENERATE_SETTLE_TIMEOUT_MS || '240000');
  flow.settled = await page
    .waitForFunction(
      () => {
        const body = document.body.innerText || '';
        const btns = [...document.querySelectorAll('button')];
        const usableGen = btns.some((b) => {
          const t = (b.textContent || '').replace(/\s+/g, ' ').trim();
          return /^Generate answers$/i.test(t) && !b.disabled;
        });
        const err =
          /Job failed|Could not check job status|Request timed out|Cannot reach the API|Generate failed|Questionnaire not found|Server error|Generation is taking|Export is taking|not have access/i.test(
            body
          );
        return usableGen || err;
      },
      { timeout: settleMs }
    )
    .then(() => true)
    .catch(() => false);

  if (!flow.settled) {
    flow.error = `Did not settle within ${settleMs}ms (job still running, worker down, or UI stuck)`;
  }

  return flow;
}

async function run() {
  const results = {
    baseUrl: BASE_URL,
    startedAt: new Date().toISOString(),
    login: { ok: false, status: null, consoleErrors: [], has161Error: false, bodySnippet: '' },
    routes: {},
    consoleByRoute: {},
    loginThenRoutes: {},
    generateFlow: null,
    allConsoleErrors: [],
    allConsoleWarnings: [],
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const consoleLogs = [];
  let currentRoute = '(global)';
  page.on('console', (msg) => {
    const type = msg.type();
    const text = msg.text();
    consoleLogs.push({ route: currentRoute, type, text });
    if (type === 'error') results.allConsoleErrors.push({ route: currentRoute, text });
    if (type === 'warning') results.allConsoleWarnings.push({ route: currentRoute, text });
    if (text && text.includes('161.js')) results.login.has161Error = true;
  });

  // 1) Prove /login loads and no 161.js error
  currentRoute = '/login';
  let response;
  try {
    response = await page.goto(BASE_URL + '/login', { waitUntil: 'domcontentloaded', timeout: 15000 });
  } catch (e) {
    results.login.error = e.message;
    await browser.close();
    output(results);
    process.exit(1);
  }
  results.login.status = response.status();
  results.login.ok = response.ok();
  const loginBody = await page.content();
  results.login.bodySnippet = loginBody.includes('Trust Copilot') ? 'Trust Copilot found' : loginBody.substring(0, 200);
  results.login.has161Error = results.allConsoleErrors.some((e) => e.text && e.text.includes('161.js'));
  results.consoleByRoute['/login'] = consoleLogs.filter((l) => l.route === '/login').map((l) => ({ type: l.type, text: l.text }));

  // 2) Visit each route (may redirect to login)
  for (const route of ROUTES) {
    if (route === '/login') continue;
    currentRoute = route;
    let status, ok, finalUrl;
    try {
      const res = await page.goto(BASE_URL + route, { waitUntil: 'domcontentloaded', timeout: 15000 });
      status = res.status();
      ok = res.ok();
      finalUrl = page.url();
    } catch (e) {
      results.routes[route] = { error: e.message };
      continue;
    }
    results.routes[route] = { status, ok, finalUrl };
    results.consoleByRoute[route] = consoleLogs.filter((l) => l.route === route).map((l) => ({ type: l.type, text: l.text }));
    const errs = (results.consoleByRoute[route] || []).filter((l) => l.type === 'error').map((l) => l.text);
    if (errs.length) results.routes[route].consoleErrors = errs;
  }

  // 3) Login and re-visit dashboard routes
  await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('input[type="email"]', 'demo@trust.local');
  await page.fill('input[type="password"]', 'j');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null),
    page.click('button[type="submit"]'),
  ]);
  const afterLoginUrl = page.url();
  results.loginThenRoutes.afterLoginUrl = afterLoginUrl;
  results.loginThenRoutes.loggedIn =
    afterLoginUrl.includes('/dashboard') ||
    (afterLoginUrl.includes(BASE_URL.replace(/^https?:\/\//, '')) && !afterLoginUrl.includes('/login'));

  const dashboardRoutes = [
    '/dashboard',
    '/dashboard/documents',
    '/dashboard/questionnaires',
    '/dashboard/review/1',
    '/dashboard/requests',
    '/dashboard/exports',
    '/dashboard/compliance-gaps',
    '/dashboard/trust-center',
  ];
  for (const route of dashboardRoutes) {
    currentRoute = 'afterLogin:' + route;
    const res = await page.goto(BASE_URL + route, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null);
    if (res) {
      results.loginThenRoutes[route] = { status: res.status(), ok: res.ok(), url: page.url() };
      const errs = consoleLogs
        .filter((l) => l.route === 'afterLogin:' + route && l.type === 'error')
        .map((l) => l.text);
      if (errs.length) results.loginThenRoutes[route].consoleErrors = errs;
    } else {
      results.loginThenRoutes[route] = { error: 'navigation failed' };
    }
  }

  // 4) Generate answers on review page (real click + wait for settle)
  currentRoute = 'generateFlow';
  results.generateFlow = await runGenerateAnswersFlow(page, BASE_URL);

  await browser.close();
  output(results);

  const f = results.generateFlow;
  if (f && !f.skipped && f.error) {
    process.exit(1);
  }
  if (f && !f.skipped && f.generatingSeen && !f.settled) {
    process.exit(1);
  }
}

function output(results) {
  const outDir = path.resolve(__dirname, '..');
  fs.writeFileSync(path.join(outDir, 'verify-browser-results.json'), JSON.stringify(results, null, 2));
  const md = toMarkdown(results);
  fs.writeFileSync(path.join(outDir, 'verify-browser-results.md'), md);
  console.log(md);
}

function toMarkdown(r) {
  const lines = [
    '# Browser verification results',
    `Base URL: ${r.baseUrl}`,
    `Started: ${r.startedAt}`,
    '',
    '## /login (first load)',
    `- Status: ${r.login.status} ${r.login.ok ? 'OK' : 'FAIL'}`,
    `- Body: ${r.login.bodySnippet}`,
    `- 161.js error in console: ${r.login.has161Error ? 'YES' : 'NO'}`,
    r.login.error ? `- Error: ${r.login.error}` : '',
    '',
    '## Routes (no auth)',
  ];
  for (const [route, data] of Object.entries(r.routes)) {
    if (data.error) lines.push(`- ${route}: ${data.error}`);
    else lines.push(`- ${route}: ${data.status} ${data.ok ? 'OK' : 'FAIL'} → ${data.finalUrl || ''}`);
    if (data.consoleErrors && data.consoleErrors.length) lines.push(`  Console errors: ${data.consoleErrors.join('; ')}`);
  }
  lines.push('', '## After login');
  lines.push(`- After login URL: ${r.loginThenRoutes.afterLoginUrl}`);
  lines.push(`- Logged in: ${r.loginThenRoutes.loggedIn}`);
  for (const route of [
    '/dashboard',
    '/dashboard/documents',
    '/dashboard/questionnaires',
    '/dashboard/review/1',
    '/dashboard/requests',
    '/dashboard/exports',
    '/dashboard/compliance-gaps',
    '/dashboard/trust-center',
  ]) {
    const d = r.loginThenRoutes[route];
    if (!d) continue;
    if (d.error) lines.push(`- ${route}: ${d.error}`);
    else lines.push(`- ${route}: ${d.status} ${d.ok ? 'OK' : 'FAIL'}`);
    if (d.consoleErrors && d.consoleErrors.length) lines.push(`  Console errors: ${d.consoleErrors.join('; ')}`);
  }

  lines.push('', '## Generate answers flow');
  const g = r.generateFlow;
  if (!g) {
    lines.push('- (not run)');
  } else if (g.skipped) {
    lines.push(`- **Skipped:** ${g.reason || 'unknown'}`);
  } else {
    lines.push(`- Questionnaire id: ${g.questionnaireId}`);
    lines.push(`- Generating UI seen: ${g.generatingSeen ? 'YES' : 'NO'}`);
    lines.push(`- Settled (button usable or error toast): ${g.settled ? 'YES' : 'NO'}`);
    if (g.error) lines.push(`- **Error:** ${g.error}`);
  }

  lines.push('', '## All console errors (by route)');
  for (const [route, errs] of Object.entries(r.consoleByRoute || {})) {
    const e = (errs || []).filter((x) => x.type === 'error').map((x) => x.text);
    if (e.length) lines.push(`- ${route}:`, ...e.map((t) => `  - ${t}`));
  }
  return lines.filter(Boolean).join('\n');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
