/**
 * Verify AI pipeline end-to-end: Trust Requests (suggest reply), Questionnaires (generate answers), Review, Export.
 * Run with app + API + worker running: BASE_URL=http://localhost:3000 node scripts/verify-ai-flows.js
 * Writes verify-ai-flows-results.json and .md
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const LOGIN_EMAIL = process.env.LOGIN_EMAIL || 'demo@trust.local';
const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || 'j';

const results = {
  baseUrl: BASE_URL,
  startedAt: new Date().toISOString(),
  questionnaires: { ok: false, questionnaireId: null, questionCount: 0, error: null, consoleErrors: [] },
  generateAnswers: { ok: false, jobCompleted: false, answersBefore: 0, answersAfter: 0, error: null, consoleErrors: [] },
  review: { ok: false, answersVisible: false, editWorked: false, error: null },
  export: { ok: false, downloadFilename: null, downloadSize: 0, error: null, consoleErrors: [] },
  allConsoleErrors: [],
  allConsoleWarnings: [],
};

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on('console', (msg) => {
    const type = msg.type();
    const text = msg.text();
    if (type === 'error') results.allConsoleErrors.push(text);
    if (type === 'warning') results.allConsoleWarnings.push(text);
  });

  try {
    // --- Login ---
    await page.goto(BASE_URL + '/login', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.fill('input[type="email"]', LOGIN_EMAIL);
    await page.fill('input[type="password"]', LOGIN_PASSWORD);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => null),
      page.click('button[type="submit"]'),
    ]);
    if (!page.url().includes('/dashboard')) {
      throw new Error('Login failed: did not reach dashboard');
    }

    // --- 1) Questionnaires – get first questionnaire id from list ---
    await page.goto(BASE_URL + '/dashboard/questionnaires', { waitUntil: 'networkidle', timeout: 15000 });
    const firstQnrLink = page.locator('a[href*="/dashboard/questionnaires/"]').first();
    const href = await firstQnrLink.getAttribute('href').catch(() => null);
    let qnrId = href ? (href.match(/\/questionnaires\/(\d+)/) || [])[1] : null;
    if (qnrId) {
      results.questionnaires.ok = true;
      results.questionnaires.questionnaireId = parseInt(qnrId, 10);
      await page.goto(BASE_URL + '/dashboard/questionnaires/' + qnrId, { waitUntil: 'networkidle', timeout: 10000 });
      const reviewLink = page.locator('a[href*="/dashboard/review/"]').first();
      const reviewHref = await reviewLink.getAttribute('href').catch(() => null);
      if (reviewHref) qnrId = (reviewHref.match(/\/review\/(\d+)/) || [])[1] || qnrId;
    } else {
      results.questionnaires.error = 'No questionnaire in list';
    }

    // --- 3) Review page – Generate answers ---
    if (qnrId) {
      await page.goto(BASE_URL + '/dashboard/review/' + qnrId, { waitUntil: 'networkidle', timeout: 15000 });
      const answerCountEl = page.locator('text=Answers').first();
      await page.waitForTimeout(1000);
      const answersText = await page.locator('strong:has-text("/")').first().textContent().catch(() => '0 / 0');
      const match = answersText.match(/(\d+)\s*\/\s*(\d+)/);
      results.generateAnswers.answersBefore = match ? parseInt(match[1], 10) : 0;
      results.generateAnswers.questionCount = match ? parseInt(match[2], 10) : 0;

      const genBtn = page.getByRole('button', { name: /Generate answers/ }).first();
      await genBtn.click();
      for (let i = 0; i < 60; i++) {
        await page.waitForTimeout(2000);
        const generating = await page.getByText('Generating…').count() > 0;
        if (!generating) break;
      }
      await page.waitForTimeout(2000);
      const answersTextAfter = await page.locator('strong:has-text("/")').first().textContent().catch(() => '0 / 0');
      const matchAfter = answersTextAfter.match(/(\d+)\s*\/\s*(\d+)/);
      results.generateAnswers.answersAfter = matchAfter ? parseInt(matchAfter[1], 10) : 0;
      results.generateAnswers.jobCompleted = true;
      results.generateAnswers.ok = results.generateAnswers.answersAfter >= results.generateAnswers.answersBefore && results.generateAnswers.answersAfter > 0;
      results.review.ok = true;
      results.review.answersVisible = results.generateAnswers.answersAfter > 0;

      // --- 4) Export – trigger job, wait for complete, then download from records ---
      const exportBtn = page.getByRole('button', { name: /Export XLSX/ }).first();
      await exportBtn.click();
      for (let i = 0; i < 45; i++) {
        await page.waitForTimeout(2000);
        const exporting = await page.getByText('Exporting…').count() > 0;
        if (!exporting) break;
      }
      await page.waitForTimeout(3000);
      const downloadBtn = page.getByRole('button', { name: 'Download' }).first();
      const [download] = await Promise.all([
        page.waitForEvent('download', { timeout: 15000 }).catch(() => null),
        downloadBtn.click(),
      ]);
      if (download) {
        const filename = download.suggestedFilename();
        const dir = path.join(__dirname, '..', 'verify-ai-downloads');
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        const savePath = path.join(dir, filename || 'export.xlsx');
        await download.saveAs(savePath);
        const stat = fs.statSync(savePath);
        results.export.downloadFilename = filename;
        results.export.downloadSize = stat.size;
        results.export.ok = stat.size > 0 && (filename || '').length > 0;
      } else {
        results.export.error = 'No download event after clicking Download';
      }
    }
  } catch (e) {
    if (!results.generateAnswers.error) results.generateAnswers.error = e.message;
    if (!results.export.error) results.export.error = e.message;
  } finally {
    await browser.close();
  }

  const outDir = path.resolve(__dirname, '..');
  fs.writeFileSync(path.join(outDir, 'verify-ai-flows-results.json'), JSON.stringify(results, null, 2));
  const md = toMarkdown(results);
  fs.writeFileSync(path.join(outDir, 'verify-ai-flows-results.md'), md);
  console.log(md);
  process.exit(results.generateAnswers.ok && results.export.ok ? 0 : 1);
}

function toMarkdown(r) {
  const lines = [
    '# AI flows verification results',
    `Base URL: ${r.baseUrl}`,
    `Started: ${r.startedAt}`,
    '',
    '## Questionnaires',
    `- OK: ${r.questionnaires.ok}`,
    `- Questionnaire ID: ${r.questionnaires.questionnaireId}`,
    r.questionnaires.error ? `- Error: ${r.questionnaires.error}` : '',
    '',
    '## Generate Answers',
    `- OK: ${r.generateAnswers.ok}`,
    `- Job completed: ${r.generateAnswers.jobCompleted}`,
    `- Answers before: ${r.generateAnswers.answersBefore}, after: ${r.generateAnswers.answersAfter}`,
    r.generateAnswers.error ? `- Error: ${r.generateAnswers.error}` : '',
    '',
    '## Review',
    `- OK: ${r.review.ok}`,
    `- Answers visible: ${r.review.answersVisible}`,
    '',
    '## Export',
    `- OK: ${r.export.ok}`,
    `- Download filename: ${r.export.downloadFilename || '(none)'}`,
    `- Download size: ${r.export.downloadSize} bytes`,
    r.export.error ? `- Error: ${r.export.error}` : '',
    '',
    '## Console errors',
    ...(r.allConsoleErrors.length ? r.allConsoleErrors.slice(0, 20).map((e) => `- ${e}`) : ['- (none)']),
  ];
  return lines.filter(Boolean).join('\n');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
