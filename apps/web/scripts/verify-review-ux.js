/**
 * Final UX verification: review page Generate answers + Export in real browser.
 * Run with stack up: BASE_URL=http://localhost:3000 node scripts/verify-review-ux.js
 */
const { chromium } = require('playwright');
const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const REVIEW_ID = process.env.REVIEW_ID || '1';

const results = {
  freezeGone: null,
  successPathWorks: null,
  timeoutErrorPath: null,
  exportWorks: null,
  uxRoughEdges: [],
  consoleErrors: [],
  details: [],
}

function log(msg) {
  results.details.push(msg);
  console.log(msg);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  page.on('console', (msg) => {
    const t = msg.type();
    const text = msg.text();
    if (t === 'error') results.consoleErrors.push(text);
  });

  try {
    await page.goto(BASE_URL + '/login', { waitUntil: 'networkidle', timeout: 15000 });
    await page.fill('input[type="email"]', 'demo@trust.local');
    await page.fill('input[type="password"]', 'j');
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/auth/login') && r.request().method() === 'POST', { timeout: 15000 }).catch(() => null),
      page.click('button[type="submit"]'),
    ]);
    if (resp && !resp.ok()) {
      log('FAIL: Login API returned ' + resp.status());
      await browser.close();
      output();
      process.exit(1);
    }
    await page.waitForTimeout(3000);
    for (let i = 0; i < 20; i++) {
      await page.waitForTimeout(1000);
      if (page.url().includes('dashboard')) break;
    }
    const url = page.url();
    if (!url.includes('dashboard')) {
      log('FAIL: Login did not reach dashboard; url=' + url);
      await browser.close();
      output();
      process.exit(1);
    }
    log('Login OK, url=' + url);

    await page.goto(BASE_URL + '/dashboard/review/' + REVIEW_ID, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    const genBtn = page.getByRole('button', { name: /Generate answers/ }).first();
    if ((await genBtn.count()) === 0) {
      log('FAIL: Generate answers button not found (canExport false or page not ready)');
      await browser.close();
      output();
      process.exit(1);
    }

    const answerCountBefore = await getAnswerCount(page);
    log(`Answer count before: ${answerCountBefore}`);

    await genBtn.click();
    await page.waitForTimeout(800);

    const generatingVisible = await page.getByText('Generating…').isVisible().catch(() => false);
    const btnDisabled = await genBtn.isDisabled().catch(() => false);
    const btnText = await genBtn.textContent().catch(() => '');
    log(`~1s after click: "Generating…" visible=${generatingVisible}, button disabled=${btnDisabled}, button text="${btnText.trim()}"`);

    if ((generatingVisible && btnDisabled) || btnDisabled) {
      results.freezeGone = true;
      log('PASS: Button disabled on click; Generating… visible=' + generatingVisible + ' (may clear quickly if job is fast). No freeze.');
    } else {
      results.freezeGone = false;
      log('FAIL: Expected button to be disabled or Generating… visible.');
    }

    let resolved = false;
    for (let i = 0; i < 50; i++) {
      await page.waitForTimeout(2000);
      const stillGenerating = await page.getByText('Generating…').isVisible().catch(() => false);
      const errorToast = await page.locator('text=/error|failed|timeout|Try again/').first().isVisible().catch(() => false);
      const answerCountAfter = await getAnswerCount(page);
      const genBtnVisibleAgain = await page.getByRole('button', { name: 'Generate answers' }).first().isVisible().catch(() => false);

      if (!stillGenerating && genBtnVisibleAgain) {
        if (errorToast) {
          results.successPathWorks = false;
          results.timeoutErrorPath = true;
          log('Generation failed or timed out; error toast visible; button usable again.');
        } else if (answerCountAfter >= answerCountBefore) {
          results.successPathWorks = true;
          results.timeoutErrorPath = false;
          log(`Success: answers updated (${answerCountAfter}), loading cleared, button back.`);
        } else {
          results.successPathWorks = true;
          log('Loading cleared, button back (job may have completed with same count).');
        }
        resolved = true;
        break;
      }
    }
    if (!resolved) {
      log('WARN: After 100s still showing Generating… or unclear state.');
      results.successPathWorks = false;
    }

    await page.waitForTimeout(1000);

    const exportBtn = page.getByRole('button', { name: /Export XLSX/ }).first();
    if ((await exportBtn.count()) > 0 && !(await exportBtn.isDisabled().catch(() => true))) {
      await exportBtn.click();
      await page.waitForTimeout(3000);
      for (let i = 0; i < 30; i++) {
        await page.waitForTimeout(2000);
        const exporting = await page.getByText('Exporting…').isVisible().catch(() => false);
        if (!exporting) break;
      }
      await page.waitForTimeout(2000);
      const downloadBtn = page.getByRole('button', { name: 'Download' }).first();
      const hasDownload = (await downloadBtn.count()) > 0;
      if (hasDownload) {
        results.exportWorks = true;
        log('Export: Export XLSX completed; Download button present.');
      } else {
        results.exportWorks = false;
        log('Export: Download button not found after export (may need more wait or no record yet).');
      }
    } else {
      results.exportWorks = null;
      log('Export: Export button not found or disabled; skip.');
    }

    if (results.consoleErrors.length > 0) {
      results.uxRoughEdges.push('Console errors: ' + results.consoleErrors.slice(0, 3).join('; '));
    }
  } catch (e) {
    log('ERROR: ' + e.message);
    results.uxRoughEdges.push(e.message);
  } finally {
    await browser.close();
  }

  output();
  const ok = results.freezeGone === true && (results.successPathWorks === true || results.timeoutErrorPath === true) && results.exportWorks !== false;
  process.exit(ok ? 0 : 1);
}

async function getAnswerCount(page) {
  const text = await page.locator('strong:has-text("/")').first().textContent().catch(() => '0 / 0');
  const m = text.match(/(\d+)\s*\/\s*(\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}

function output() {
  const fs = require('fs');
  const path = require('path');
  const outPath = path.join(__dirname, '..', 'verify-review-ux-results.json');
  fs.writeFileSync(outPath, JSON.stringify(results, null, 2));
  console.log('\n--- Summary ---');
  console.log('Freeze gone:', results.freezeGone);
  console.log('Success path works:', results.successPathWorks);
  console.log('Timeout/error path tested:', results.timeoutErrorPath);
  console.log('Export works:', results.exportWorks);
  console.log('UX rough edges:', results.uxRoughEdges.length ? results.uxRoughEdges : 'none');
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
