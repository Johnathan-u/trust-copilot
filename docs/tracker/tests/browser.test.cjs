/* Run with the existing web workspace dependency:
 * node --test docs/tracker/tests/browser.test.cjs
 * Optional: BACKLOG_DATA_PATH, PLAYWRIGHT_BROWSERS_PATH,
 * BACKLOG_SCREENSHOT_DIR, and BACKLOG_BROWSER_EXECUTABLE.
 * No network service or application server is needed.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const vm = require('node:vm');
const { before, after, test } = require('node:test');
const { createRequire } = require('node:module');

const root = path.resolve(__dirname, '../../..');
const tracker = path.join(root, 'docs/tracker');
const webRequire = createRequire(path.join(root, 'apps/web/package.json'));
let playwright;
try { playwright = webRequire('playwright'); }
catch { playwright = require('playwright'); }
const canonical = JSON.parse(fs.readFileSync(path.join(root, 'docs/planning/TrustCopilot_Execution_Backlog.json'), 'utf8'));
const dataPath = process.env.BACKLOG_DATA_PATH || path.join(tracker, 'data.js');
let server, browser, origin;
const issues = [];

function snapshot() {
  const scope = { window: {} };
  vm.runInNewContext(fs.readFileSync(dataPath, 'utf8'), scope);
  return JSON.parse(JSON.stringify(scope.window.TRUSTCOPILOT_BACKLOG));
}

// Deterministic UI states derived from the full canonical dataset. These in-memory
// fixtures never write the repository ledger or claim real acceptance evidence.
function acceptanceFixture(accepted = false) {
  const data = snapshot();
  const state = accepted ? 'VERIFIED' : 'PENDING';
  data.meta.baseline_status = state;
  Object.assign(data.summary, { baseline_status: state, accepted_points: accepted ? 1864 : null, completion_percentage: accepted ? 100 : null, assessed_tickets: accepted ? 384 : 0, accepted_tickets: accepted ? 384 : 0, accepted_claim_points: accepted ? 1864 : 0, state_counts: { [accepted ? 'DONE' : 'BASELINE_RECONCILIATION']: 384 } });
  for (const ticket of data.tickets) {
    ticket.current.status = accepted ? 'DONE' : 'BASELINE_RECONCILIATION';
    ticket.current.owner = accepted ? 'fixture-implementer' : null;
    ticket.current.blockers = [];
    const evidence = accepted ? ['https://example.invalid/browser-test/acceptance'] : [];
    Object.assign(ticket.current.acceptance, { state: accepted ? 'ACCEPTED' : 'PENDING', assessed_by: accepted ? 'fixture-reviewer' : null, assessed_at: accepted ? data.meta.as_of_utc : null, assessed_sha: accepted ? data.meta.source_sha : null, assessment_evidence_urls: evidence, tested_sha: accepted ? data.meta.source_sha : null, implemented_by: accepted ? ['fixture-implementer'] : [], independent_reviewer: accepted ? 'fixture-reviewer' : null, reviewed_at: accepted ? data.meta.as_of_utc : null, reviewed_sha: accepted ? data.meta.source_sha : null, review_evidence_urls: evidence, note: 'In-memory browser test fixture only.' });
    for (const criterion of [...ticket.current.acceptance.criteria, ...ticket.current.acceptance.definition_of_done]) Object.assign(criterion, { status: accepted ? 'PASS' : 'NOT_VERIFIED', evidence_urls: evidence, tested_sha: accepted ? data.meta.source_sha : null });
  }
  for (const epic of data.epics) Object.assign(epic.rollup, { assessed_tickets: accepted ? epic.ticket_count : 0, accepted_tickets: accepted ? epic.ticket_count : 0, accepted_points: accepted ? epic.story_points : null, state_counts: { [accepted ? 'DONE' : 'BASELINE_RECONCILIATION']: epic.ticket_count } });
  return data;
}

before(async () => {
  server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const relative = pathname === '/' ? 'index.html' : decodeURIComponent(pathname).replace(/^\/+/, '');
    const file = relative === 'data.js' ? dataPath : path.resolve(tracker, relative);
    if (relative !== 'data.js' && !file.startsWith(tracker + path.sep)) {
      response.writeHead(403).end(); return;
    }
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404, { 'Content-Type': 'text/html' }).end('<!doctype html><html lang="en"><title>Missing asset</title><body>Tracker asset is not implemented.</body></html>'); return;
    }
    response.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript' })[path.extname(file)] || 'text/plain' });
    fs.createReadStream(file).pipe(response);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await playwright.chromium.launch({ headless: true, ...(process.env.BACKLOG_BROWSER_EXECUTABLE ? { executablePath: process.env.BACKLOG_BROWSER_EXECUTABLE } : {}) });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
});

async function open(hash = '', viewport = { width: 1440, height: 1000 }, fixture = null) {
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
  if (fixture) await context.route('**/data.js', route => route.fulfill({ contentType: 'text/javascript', body: `window.TRUSTCOPILOT_BACKLOG=${JSON.stringify(fixture)};` }));
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => issues.push(error.message));
  await page.goto(origin + '/' + hash);
  return { page, context };
}

async function screenshot(page, name) {
  if (!process.env.BACKLOG_SCREENSHOT_DIR) return;
  fs.mkdirSync(process.env.BACKLOG_SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: path.join(process.env.BACKLOG_SCREENSHOT_DIR, name + '.png'), fullPage: name.startsWith('overview'), timeout: 15000 });
}

test('pending baseline never becomes a fabricated completion percentage', async () => {
  const { page, context } = await open('', undefined, acceptanceFixture());
  try {
    assert.ok(await page.getByRole('heading', { name: 'Release overview', exact: true }).isVisible(), 'The implemented overview must be available');
    assert.match(await page.locator('#acceptance-progress').innerText(), /Baseline pending/);
    assert.doesNotMatch(await page.locator('#acceptance-progress').innerText(), /\b(?:0|45)(?:\.0)?\s*%/);
    assert.equal(await page.locator('[data-metric="tickets"]').innerText(), '384');
    assert.equal(await page.locator('[data-metric="epics"]').innerText(), '30');
    assert.equal(await page.locator('[data-metric="points"]').innerText(), '1,864');
    const data = snapshot();
    assert.match(await page.locator('#snapshot-provenance').innerText(), new RegExp(data.meta.source_sha.slice(0, 12)));
    assert.match(await page.locator('#snapshot-provenance').innerText(), /UTC/);
    assert.match(await page.locator('#snapshot-notice').innerText(), /Static snapshot/);
  } finally { await context.close(); }
});

test('the full original backlog is searchable and filters combine without hiding reset', async () => {
  const { page, context } = await open('#backlog');
  try {
    assert.equal(await page.locator('[data-ticket-row]').count(), 384);
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('TC-01-003');
    assert.deepEqual(await page.locator('[data-ticket-row]').evaluateAll(rows => rows.map(row => row.dataset.ticketRow)), ['TC-01-003']);
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('PyMuPDF');
    assert.ok(await page.locator('[data-ticket-row="TC-01-003"]').isVisible());
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('prior public grants');
    assert.ok(await page.locator('[data-ticket-row="TC-01-002"]').isVisible());
    assert.ok(await page.locator('[data-ticket-row="TC-30-004"]').isVisible());
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('docs/acceptance/ip-provenance.md');
    assert.ok(await page.locator('[data-ticket-row="TC-01-002"]').isVisible());
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('');
    await page.getByLabel('Epic', { exact: true }).selectOption('E01');
    await page.getByLabel('Priority', { exact: true }).selectOption('P0');
    const expected = canonical.tickets.filter(ticket => ticket.epic === 'E01' && ticket.priority === 'P0').map(ticket => ticket.id);
    assert.deepEqual(await page.locator('[data-ticket-row]').evaluateAll(rows => rows.map(row => row.dataset.ticketRow)), expected);
    const status = snapshot().tickets.find(ticket => ticket.epic === 'E01').current.status;
    await page.getByLabel('Recorded status', { exact: true }).selectOption(status);
    assert.deepEqual(await page.locator('[data-ticket-row]').evaluateAll(rows => rows.map(row => row.dataset.ticketRow)), snapshot().tickets.filter(ticket => ticket.epic === 'E01' && ticket.priority === 'P0' && ticket.current.status === status).map(ticket => ticket.id));
    await page.getByLabel('Assigned owner', { exact: true }).selectOption('__unassigned__');
    const unassigned = snapshot().tickets.filter(ticket => ticket.epic === 'E01' && ticket.priority === 'P0' && ticket.current.status === status && !ticket.current.owner).map(ticket => ticket.id);
    assert.deepEqual(await page.locator('[data-ticket-row]').evaluateAll(rows => rows.map(row => row.dataset.ticketRow)), unassigned);
    await page.getByRole('searchbox', { name: 'Search backlog' }).fill('zz-no-such-ticket-zz');
    assert.ok(await page.getByRole('heading', { name: 'No matching tickets' }).isVisible());
    await page.getByRole('button', { name: 'Reset filters', exact: true }).first().click();
    assert.equal(await page.locator('[data-ticket-row]').count(), 384);
    await screenshot(page, 'backlog-desktop');
  } finally { await context.close(); }
});

test('ticket deep links expose complete criteria and dependencies with keyboard focus restoration', async () => {
  const ticket = canonical.tickets.find(item => item.id === 'TC-01-003');
  const { page, context } = await open('#backlog');
  try {
    await page.getByRole('navigation', { name: 'Project navigation' }).getByRole('link', { name: 'Backlog', exact: true }).click();
    const link = page.locator('[data-ticket-row="TC-01-003"] a[data-open-ticket]');
    await link.focus();
    await page.keyboard.press('Enter');
    assert.match(page.url(), /ticket=TC-01-003/);
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ state: 'visible' });
    const text = await dialog.innerText();
    for (const field of ['acceptance_criteria', 'definition_of_done', 'definition_of_ready', 'implementation_steps', 'files_review_modify', 'files_create']) {
      for (const value of ticket[field]) assert.ok(text.includes(value), `Missing ${field}: ${value}`);
    }
    assert.ok(text.includes(ticket.test_command));
    assert.ok(text.includes(ticket.interfaces.consumes));
    assert.ok(text.includes(ticket.interfaces.produces));
    assert.match(text, /Historical planning status/);
    assert.match(text, /Expected owner role/);
    const owner = snapshot().tickets.find(item => item.id === ticket.id).current.owner;
    assert.ok(text.includes(owner || 'Unassigned'));
    await page.keyboard.press('Escape');
    assert.equal(await dialog.isVisible(), false);
    assert.equal(await link.evaluate(element => element === document.activeElement), true);
    await page.goto(origin + '/#ticket=TC-01-003');
    assert.ok(await dialog.isVisible());
    await dialog.locator('[data-dependency="TC-01-002"]').click();
    await page.waitForFunction(() => document.querySelector('#ticket-dialog > .drawer-header > .ticket-id')?.textContent === 'TC-01-002');
    assert.match(page.url(), /ticket=TC-01-002/);
    assert.ok((await dialog.innerText()).includes('TC-01-002'));
    await screenshot(page, 'ticket-desktop');
  } finally { await context.close(); }
});

test('all views remain navigable on a small viewport and the drawer stays within the screen', async () => {
  const { page, context } = await open('', { width: 390, height: 844 });
  try {
    for (const name of ['Backlog', 'Epics', 'Release gates', 'PM handoff', 'History', 'Overview']) {
      await page.getByRole('navigation', { name: 'Project navigation' }).getByRole('link', { name, exact: true }).click();
      const headings = { Backlog: 'Full backlog', Epics: 'Epic portfolio', 'Release gates': 'Release gates', 'PM handoff': 'PM handoff', History: 'Change history', Overview: 'Release overview' };
      await page.getByRole('heading', { name: headings[name], exact: true, level: 1 }).waitFor({ state: 'visible' });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Horizontal overflow in ${name}`);
    }
    await screenshot(page, 'overview-mobile');
    await page.goto(origin + '/#backlog');
    assert.ok(await page.locator('[data-ticket-row="TC-01-003"]').isVisible());
    await screenshot(page, 'backlog-mobile');
    await page.locator('[data-ticket-row="TC-01-003"] a[data-open-ticket]').click();
    const bounds = await page.getByRole('dialog').boundingBox();
    assert.ok(bounds.width <= 390 && bounds.x >= 0);
    assert.ok(await page.getByRole('button', { name: 'Close ticket' }).isVisible());
    await screenshot(page, 'ticket-mobile');
    await page.keyboard.press('Escape');
    assert.equal(await page.getByRole('dialog').isVisible(), false);
  } finally { await context.close(); }
});

test('untrusted source text stays inert and unsafe links never become clickable', async () => {
  const context = await browser.newContext();
  const data = snapshot();
  data.tickets[0].title = '<img src=x onerror="window.trackerInjected=true">';
  data.tickets[0].current.next_action = '<script>window.trackerInjected=true</script>';
  data.tickets[0].current.evidence_links.push('javascript:window.trackerInjected=true', 'data:text/html,<script>alert(1)</script>', 'https://github.com/example/repo/blob/main/%');
  data.tickets[0].current.pr_links.push({ url: 'javascript:window.trackerInjected=true', title: 'Unsafe test link', number: 1 });
  await context.route('**/data.js', route => route.fulfill({ contentType: 'text/javascript', body: `window.TRUSTCOPILOT_BACKLOG=${JSON.stringify(data)};` }));
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const sourceErrors = [];
  page.on('pageerror', error => sourceErrors.push(error.message));
  try {
    await page.goto(origin + '/#ticket=' + data.tickets[0].id);
    assert.deepEqual(sourceErrors, [], 'Malformed source URLs must not crash rendering');
    const dialog = page.getByRole('dialog');
    assert.ok((await dialog.innerText()).includes(data.tickets[0].title));
    assert.equal(await page.evaluate(() => window.trackerInjected), undefined);
    assert.equal(await dialog.locator('img, script').count(), 0);
    assert.equal(await page.locator('a[href^="javascript:"], a[href^="data:"]').count(), 0);
  } finally { await context.close(); }
});

test('snapshot export preserves all records and file URL mode works without external requests', async () => {
  const { page, context } = await open();
  try {
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export snapshot', exact: true }).click();
    const download = await downloadPromise;
    const exported = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
    assert.equal(exported.tickets.length, 384);
    assert.equal(exported.summary.total_points, 1864);
    assert.equal(exported.meta.source_sha, snapshot().meta.source_sha);
    // A real offline copy includes the generated data alongside the three UI files.
    const os = require('node:os');
    const offline = fs.mkdtempSync(path.join(os.tmpdir(), 'tracker-offline-'));
    try {
      for (const file of ['index.html', 'styles.css', 'app.js']) fs.copyFileSync(path.join(tracker, file), path.join(offline, file));
      fs.copyFileSync(dataPath, path.join(offline, 'data.js'));
      const requests = [];
      page.on('request', request => requests.push(request.url()));
      await context.setOffline(true);
      await page.goto(require('node:url').pathToFileURL(path.join(offline, 'index.html')).href + '#ticket=TC-01-003');
      assert.ok(await page.getByRole('dialog').isVisible());
      assert.equal(requests.filter(url => /^https?:/.test(url)).length, 0);
    } finally { fs.rmSync(offline, { recursive: true, force: true }); }
  } finally { await context.close(); }
});

test('an aged snapshot is labeled stale while its original provenance stays visible', async () => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  try {
    const data = snapshot();
    await page.clock.setFixedTime(new Date(Date.parse(data.meta.as_of_utc) + 48 * 60 * 60 * 1000));
    await page.goto(origin + '/#backlog');
    assert.match(await page.locator('#snapshot-notice').innerText(), /older than 24 hours \(2 days\)/);
    assert.equal(await page.locator('#source-time').getAttribute('title'), data.meta.as_of_utc);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const bounds = await page.locator('#snapshot-provenance').boundingBox();
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844);
    assert.match(await page.locator('#snapshot-provenance').innerText(), new RegExp(data.meta.source_sha.slice(0, 12)));
  } finally { await context.close(); }
});

test('effective engineering prerequisites apply R1 and R2 and preserve the original dependency record', async () => {
  const { page, context } = await open('#ticket=TC-12-004');
  try {
    const dialog = page.getByRole('dialog');
    assert.deepEqual(await dialog.locator('[data-dependency-scope="engineering"] [data-dependency]').evaluateAll(nodes => nodes.map(node => node.dataset.dependency)), ['TC-12-002', 'TC-12-003']);
    assert.match(await dialog.getByRole('link', { name: 'Read scope-freeze ruling R1' }).getAttribute('href'), /scope-freeze\.md#8-/);
    await dialog.getByText('Original planning dependencies', { exact: true }).click();
    assert.deepEqual(await dialog.locator('[data-dependency-scope="original"] [data-original-dependency]').evaluateAll(nodes => nodes.map(node => node.dataset.originalDependency)), ['TC-11-003', 'TC-11-001', 'TC-06-001']);
    await page.goto(origin + '/#ticket=TC-26-018');
    await page.waitForFunction(() => document.querySelector('#ticket-dialog > .drawer-header > .ticket-id')?.textContent === 'TC-26-018');
    assert.deepEqual(await dialog.locator('[data-dependency-scope="engineering"] [data-dependency]').evaluateAll(nodes => nodes.map(node => node.dataset.dependency)), ['TC-26-014', 'TC-07-011']);
    assert.equal(await dialog.locator('[data-dependency-scope="engineering"] [data-dependency="TC-24-005"]').count(), 0);
    assert.ok(await dialog.getByRole('link', { name: 'Read scope-freeze ruling R2' }).isVisible());
    await dialog.getByText('Original planning dependencies', { exact: true }).click();
    assert.ok(await dialog.locator('[data-original-dependency="TC-24-005"]').isVisible());
  } finally { await context.close(); }
});

test('legal decisions gate release separately while transfer hard dependencies remain intact', async () => {
  const { page, context } = await open('#ticket=TC-21-001');
  try {
    const dialog = page.getByRole('dialog');
    assert.equal(await dialog.locator('[data-dependency-scope="engineering"] [data-dependency]').count(), 0);
    assert.deepEqual(await dialog.locator('[data-dependency-scope="release"] [data-dependency]').evaluateAll(nodes => nodes.map(node => node.dataset.dependency)), ['TC-01-003', 'TC-01-007']);
    assert.ok(await dialog.getByRole('link', { name: 'Read scope-freeze ruling R4' }).isVisible());
    const rights = dialog.locator('[data-dependency-scope="release"] [data-dependency="TC-01-007"]');
    const source = snapshot().followups.find(item => item.id === 'TC-01-007');
    assert.equal(await rights.getAttribute('href'), source.source_url);
    assert.doesNotMatch(await rights.getAttribute('href'), /#.*ticket=/);
    for (const [id, expected] of [
      ['TC-29-006', ['TC-28-006', 'TC-01-004', 'TC-01-002']],
      ['TC-30-004', ['TC-29-006', 'TC-01-002']],
    ]) {
      await page.goto(origin + '/#ticket=' + id);
      await page.waitForFunction(id => document.querySelector('#ticket-dialog > .drawer-header > .ticket-id')?.textContent === id, id);
      assert.deepEqual(await dialog.locator('[data-dependency-scope="engineering"] [data-dependency]').evaluateAll(nodes => nodes.map(node => node.dataset.dependency)), expected);
      assert.equal(await dialog.locator('[data-dependency-scope="release"] [data-dependency]').count(), 0);
      assert.ok(await dialog.getByRole('link', { name: 'Read scope-freeze ruling R4' }).isVisible());
    }
  } finally { await context.close(); }
});

test('later state metadata and current PR links do not refresh the immutable initial audit registries', async () => {
  const context = await browser.newContext();
  const data = snapshot();
  const auditTime = data.audit_context.as_of_utc;
  const auditSHA = data.audit_context.source_sha;
  const laterTime = new Date(Date.parse(auditTime) + 24 * 60 * 60 * 1000).toISOString();
  const laterSHA = 'a'.repeat(40);
  data.meta.as_of_utc = laterTime;
  data.meta.source_sha = laterSHA;
  data.tickets.find(ticket => ticket.id === 'TC-01-002').current.pr_links = [{ number: 98765, title: 'Current-state evidence fixture', url: 'https://example.invalid/pr/98765', state: 'open', head_sha: laterSHA }];
  await context.route('**/data.js', route => route.fulfill({ contentType: 'text/javascript', body: `window.TRUSTCOPILOT_BACKLOG=${JSON.stringify(data)};` }));
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  try {
    await page.goto(origin + '/#handoff');
    assert.equal(await page.locator('#source-time').getAttribute('title'), laterTime);
    assert.match(await page.locator('#source-sha').innerText(), /aaaaaaaaaaaa/);
    for (const id of ['initial-pr-registry', 'initial-reconciliation-queue']) {
      const registry = page.locator('#' + id);
      assert.match(await registry.innerText(), /Initial audit/);
      assert.equal(await registry.locator('[data-initial-audit-time]').getAttribute('datetime'), auditTime);
      assert.equal(await registry.locator('[data-initial-audit-sha]').getAttribute('title'), auditSHA);
      assert.match(await registry.innerText(), /Later state updates do not refresh/);
    }
    await page.goto(origin + '/#ticket=TC-01-002');
    const current = page.locator('[data-current-pr-links]');
    assert.match(await current.innerText(), /Current recorded PR links/);
    assert.ok(await current.getByRole('link', { name: '#98765 · Current-state evidence fixture', exact: true }).isVisible());
  } finally { await context.close(); }
});

test('a timestamp on a pending partial assessment does not inflate epic assessment coverage', async () => {
  const context = await browser.newContext();
  const data = acceptanceFixture();
  data.tickets.find(ticket => ticket.id === 'TC-01-001').current.acceptance.assessed_at = data.meta.as_of_utc;
  await context.route('**/data.js', route => route.fulfill({ contentType: 'text/javascript', body: `window.TRUSTCOPILOT_BACKLOG=${JSON.stringify(data)};` }));
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  try {
    await page.goto(origin + '/#epics');
    const epic = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Product scope and ownership', exact: true }) });
    assert.match(await epic.locator('.epic-bottom').innerText(), /0 \/ 6 assessed/);
  } finally { await context.close(); }
});

test('a direct skip-to-content URL loads the overview before focusing the main content', async () => {
  const { page, context } = await open('#main');
  try {
    assert.ok(await page.getByRole('heading', { name: 'Release overview', exact: true, level: 1 }).isVisible());
    assert.equal(await page.locator('#main').evaluate(node => node === document.activeElement), true);
    assert.equal(await page.locator('#boot-status').count(), 0);
  } finally { await context.close(); }
});

test('the live snapshot overview agrees with its generated acceptance baseline', async () => {
  const { page, context } = await open();
  try {
    const data = snapshot();
    const progress = await page.locator('#acceptance-progress').innerText();
    if (data.meta.baseline_status === 'VERIFIED') {
      assert.ok(progress.includes(data.summary.completion_percentage.toLocaleString('en-US') + '% accepted'));
      assert.ok(progress.includes(data.summary.accepted_points.toLocaleString('en-US') + ' / 1,864'));
    } else {
      assert.match(progress, /Baseline pending/);
      assert.match(progress, /Unknown \/ 1,864/);
    }
    assert.equal(await page.locator('[data-metric="assessed"]').innerText(), data.summary.assessed_tickets.toLocaleString('en-US'));
    assert.equal(await page.locator('#source-time').getAttribute('title'), data.meta.as_of_utc);
    await screenshot(page, 'overview-desktop');
  } finally { await context.close(); }
});

test('a fully assessed accepted baseline displays its verified weighted completion', async () => {
  const { page, context } = await open('', undefined, acceptanceFixture(true));
  try {
    const progress = await page.locator('#acceptance-progress').innerText();
    assert.match(progress, /100% accepted/);
    assert.match(progress, /1,864 \/ 1,864/);
    assert.doesNotMatch(progress, /Baseline pending|Unknown \/ 1,864/);
    assert.equal(await page.locator('[data-metric="assessed"]').innerText(), '384');
  } finally { await context.close(); }
});

test('browser scripts complete without runtime errors', () => {
  assert.deepEqual(issues, []);
});
