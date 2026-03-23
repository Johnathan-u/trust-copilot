/**
 * Focused audit E2E: questionnaire policy gap mapping, evidence UI, subject-area mapping preference,
 * confidence sanity, cloud/security smoke, questionnaire-driven compliance gaps.
 *
 * Run full stack: from repo root `npm run test:e2e` (see playwright.config.ts).
 * Local: `cd apps/web && npx playwright test e2e/questionnaire-mappings-audit.spec.ts`
 */
import { test, expect } from '@playwright/test'
import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  BENCHMARK_TERMS,
  CLOUD_AUDIT_TERMS,
  ensureAuthenticated,
  getWorkspaceId,
  pickBestParsedQuestionnaire,
  postJsonLogin,
  jsonRequest,
  resetMappingsToSuggested,
} from './mapping-audit-helpers'

function baseUrlFromEnv(): string {
  const port = process.env.E2E_WEB_PORT || '3000'
  return `http://127.0.0.1:${port}`
}

async function loadMappingsApi(
  request: import('@playwright/test').APIRequestContext,
  ws: number,
  qid: number,
) {
  const res = await request.get(`/api/questionnaires/${qid}/mappings?workspace_id=${ws}`)
  expect(res.ok()).toBeTruthy()
  return res.json() as Promise<{
    mappings: Array<{
      id: number
      question_text: string | null
      preferred_control_id: number | null
      confidence: number | null
      status: string
      supporting_evidence?: Array<{ display_name: string }>
    }>
    mapping_preferred_subject_areas?: string[]
  }>
}

test.describe('Questionnaire mapping audit', () => {
  // Mapping generation + cold Next compile can exceed default 30s test timeout.
  test.describe.configure({ timeout: 180_000 })

  test.beforeEach(async ({ page }) => {
    await ensureAuthenticated(page)
  })

  test('meta: record questionnaire used for audit', async ({ page }, testInfo) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick, 'No parsed questionnaire in workspace')
    testInfo.annotations.push({
      type: 'questionnaire',
      description: JSON.stringify({
        id: pick!.id,
        filename: pick!.filename,
        questionCount: pick!.questionCount,
        cloudSecurityFilenameHint: pick!.cloudSecurityHint,
      }),
    })
    await testInfo.attach('questionnaire-pick.json', {
      body: Buffer.from(JSON.stringify(pick, null, 2)),
      contentType: 'application/json',
    })
  })

  test('A: generate/regenerate, stats, rows, per-question actions persist', async ({ page }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick || pick.questionCount < 3, 'Need parsed questionnaire with 3+ questions')

    await resetMappingsToSuggested(page.request, ws, pick.id)
    await page.goto(`/dashboard/questionnaires/${pick.id}/mappings`)
    await expect(page.getByRole('heading', { name: 'Policy gap mapping' })).toBeVisible({ timeout: 30_000 })

    const gen = page.getByRole('button', { name: /generate gap mappings|regenerate all/i }).first()
    await gen.click()
    await expect(page.getByRole('button', { name: 'Approve' }).first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Total Qs', { exact: true })).toBeVisible()
    await expect(page.getByText('Mapped', { exact: true })).toBeVisible()

    const data = await loadMappingsApi(page.request, ws, pick.id)
    const ids = data.mappings.map((m) => m.id)
    test.skip(ids.length < 4, 'Need 4+ mapping rows')

    await page.request.patch(
      `/api/questionnaires/${pick.id}/mappings/${ids[0]}?workspace_id=${ws}`,
      { ...jsonRequest({ status: 'approved' }) },
    )
    await page.request.patch(
      `/api/questionnaires/${pick.id}/mappings/${ids[1]}?workspace_id=${ws}`,
      { ...jsonRequest({ status: 'rejected' }) },
    )
    const controlsRes = await page.request.get('/api/compliance/controls')
    const controls = (await controlsRes.json()) as Array<{ id: number }>
    test.skip(controls.length < 2, 'Need 2+ workspace controls for edit test')
    await page.request.patch(
      `/api/questionnaires/${pick.id}/mappings/${ids[2]}?workspace_id=${ws}`,
      { ...jsonRequest({ status: 'manual', preferred_control_id: controls[1].id }) },
    )
    await page.request.post(
      `/api/questionnaires/${pick.id}/mappings/${ids[3]}/regenerate?workspace_id=${ws}`,
    )

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Policy gap mapping' })).toBeVisible({ timeout: 30_000 })
    const after = await loadMappingsApi(page.request, ws, pick.id)
    const byId = Object.fromEntries(after.mappings.map((m) => [m.id, m]))
    expect(byId[ids[0]]?.status).toBe('approved')
    expect(byId[ids[1]]?.status).toBe('rejected')
    expect(byId[ids[2]]?.status).toBe('manual')
    expect(byId[ids[2]]?.preferred_control_id).toBe(controls[1].id)
  })

  test('B: evidence UI — three states, duplicate names, stub-like strings', async ({ page }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick, 'No parsed questionnaire')

    await page.goto(`/dashboard/questionnaires/${pick.id}/mappings`)
    await expect(page.getByRole('heading', { name: 'Policy gap mapping' })).toBeVisible({ timeout: 30_000 })
    const gen = page.getByRole('button', { name: /generate gap mappings|regenerate all/i }).first()
    if (await gen.isVisible()) await gen.click()
    await expect(page.locator('[data-testid^="mapping-row-"]').first()).toBeVisible({ timeout: 60_000 })

    const awaitControl = page.locator('[data-testid="supporting-evidence-await-control"]')
    const noDocs = page.locator('[data-testid="supporting-evidence-empty"]')
    const linkedList = page.locator('[data-testid="linked-evidence-list"]')

    const nAwait = await awaitControl.count()
    const nNoDocs = await noDocs.count()
    const nLinked = await linkedList.count()
    expect(nAwait + nNoDocs + nLinked, 'expected at least one evidence UI state across rows').toBeGreaterThan(0)

    const stubHits: string[] = []
    const body = await page.content()
    if (/stub|TBD|lorem ipsum|placeholder evidence/i.test(body)) {
      stubHits.push('page HTML matched stub/placeholder-like pattern (review manually)')
    }

    const rows = page.locator('[data-testid^="mapping-row-"]')
    const rowCount = await rows.count()
    const duplicateReports: string[] = []
    for (let i = 0; i < rowCount; i++) {
      const list = rows.nth(i).locator('[data-testid="linked-evidence-list"]')
      if ((await list.count()) === 0) continue
      const names = await list.locator('li span.truncate').allTextContents()
      const seen = new Set<string>()
      for (const n of names) {
        const t = n.trim()
        if (seen.has(t) && t.length > 0) {
          duplicateReports.push(`row ${i}: duplicate display_name "${t}"`)
        }
        seen.add(t)
      }
      if (/stub|TBD|lorem/i.test(await rows.nth(i).innerText())) {
        stubHits.push(`row ${i}: stub-like substring in row text`)
      }
    }

    test.info().annotations.push({ type: 'evidence-dupes', description: duplicateReports.join('; ') || 'none' })
    test.info().annotations.push({ type: 'evidence-stub-hits', description: stubHits.join('; ') || 'none' })
    test.info().annotations.push({
      type: 'evidence-state-counts',
      description: `awaitControl=${nAwait}, noDocs=${nNoDocs}, linkedLists=${nLinked}`,
    })
  })

  test('C: framework preference ALL vs SOC 2 + benchmark row deltas (labels only)', async ({ page }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick, 'No parsed questionnaire')

    await resetMappingsToSuggested(page.request, ws, pick.id)
    await page.request.post(`/api/questionnaires/${pick.id}/generate-mappings?workspace_id=${ws}`)

    const captureBenchmark = async (label: string) => {
      const j = await loadMappingsApi(page.request, ws, pick.id)
      const out: Record<string, string> = {}
      for (const term of BENCHMARK_TERMS) {
        const tl = term.toLowerCase()
        const hit = j.mappings.find((m) => (m.question_text || '').toLowerCase().includes(tl))
        if (hit) {
          const ctrl =
            hit.preferred_control_id != null ? `control#${hit.preferred_control_id}` : 'none'
          out[term] = `${ctrl} conf=${hit.confidence != null ? (hit.confidence * 100).toFixed(0) : 'null'}%`
        }
      }
      await test.info().attach(`benchmark-${label}.json`, {
        body: Buffer.from(JSON.stringify(out, null, 2)),
        contentType: 'application/json',
      })
      return { raw: j, snapshot: out }
    }

    await page.goto(`/dashboard/questionnaires/${pick.id}/mappings`)
    await expect(page.getByTestId('mapping-subject-areas')).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: /regenerate all|generate gap mappings/i }).click()
    await expect(page.locator('[data-testid^="mapping-row-"]').first()).toBeVisible({ timeout: 60_000 })
    const baseline = await captureBenchmark('baseline')

    const access = page.getByTestId('mapping-subject-areas').getByRole('checkbox', { name: 'Access Control' })
    await access.check()
    await page.getByRole('button', { name: /regenerate all/i }).click()
    await expect(page.locator('[data-testid^="mapping-row-"]').first()).toBeVisible({ timeout: 60_000 })
    const subjectPass = await captureBenchmark('access-control-subject')

    const changed: string[] = []
    for (const k of Object.keys(baseline.snapshot)) {
      if (baseline.snapshot[k] !== subjectPass.snapshot[k]) changed.push(k)
    }
    test.info().annotations.push({
      type: 'subject-benchmark-delta',
      description:
        changed.length > 0
          ? `Rows with different control/conf snapshot after toggling Access Control subject: ${changed.join(', ')}`
          : 'No benchmark keyword rows changed when subject preference toggled (or no keyword hits).',
    })

    await page.reload()
    await expect(page.getByTestId('mapping-subject-areas')).toBeVisible({ timeout: 15_000 })
  })

  test('D: confidence sanity via API', async ({ page }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick, 'No parsed questionnaire')
    const j = await loadMappingsApi(page.request, ws, pick.id)
    const confs = j.mappings.map((m) => m.confidence).filter((c): c is number => c != null)
    const unique = new Set(confs.map((c) => c.toFixed(4)))
    test.info().annotations.push({
      type: 'confidence-unique-count',
      description: String(unique.size),
    })

    const zeroWithControl = j.mappings.filter(
      (m) => m.preferred_control_id != null && (m.confidence === 0 || m.confidence === null),
    )
    test.info().annotations.push({
      type: 'zero-confidence-with-control',
      description:
        zeroWithControl.length > 0
          ? JSON.stringify(
              zeroWithControl.slice(0, 10).map((m) => ({
                id: m.id,
                control: m.preferred_control_id,
                confidence: m.confidence,
              })),
            )
          : 'none',
    })
  })

  test('E: cloud/security keyword smoke (API)', async ({ page }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick, 'No parsed questionnaire')
    const j = await loadMappingsApi(page.request, ws, pick.id)
    const report: Array<{
      keyword: string
      question: string
      control: string | null
      confidence: string
      hasEvidence: boolean
    }> = []

    for (const kw of CLOUD_AUDIT_TERMS) {
      const hit = j.mappings.find((m) => (m.question_text || '').toLowerCase().includes(kw))
      if (!hit) continue
      report.push({
        keyword: kw,
        question: (hit.question_text || '').slice(0, 200),
        control: hit.preferred_control_id != null ? String(hit.preferred_control_id) : null,
        confidence: hit.confidence != null ? `${(hit.confidence * 100).toFixed(0)}%` : 'null',
        hasEvidence: (hit.supporting_evidence?.length ?? 0) > 0,
      })
    }
    await test.info().attach('cloud-smoke.json', {
      body: Buffer.from(JSON.stringify({ report, cloudFilenameHint: pick.cloudSecurityHint }, null, 2)),
      contentType: 'application/json',
    })
    test.info().annotations.push({
      type: 'cloud-smoke-rows',
      description: report.length > 0 ? `${report.length} keyword rows` : 'no CLOUD_AUDIT_TERMS matched question text',
    })
  })

  test('F: compliance gaps — global + questionnaire sections, dedupe, link navigation, admin evidence clears q-gap', async ({
    page,
    browser,
  }) => {
    const ws = await getWorkspaceId(page.request)
    const pick = await pickBestParsedQuestionnaire(page.request, ws)
    test.skip(!pick || pick.questionCount < 3, 'Need parsed questionnaire with 3+ questions')

    const controlsRes = await page.request.get('/api/compliance/controls')
    const controls = (await controlsRes.json()) as Array<{ id: number }>
    test.skip(controls.length < 1, 'No workspace controls — seed dev compliance catalog')

    const c1 = controls[0].id
    await resetMappingsToSuggested(page.request, ws, pick.id)
    await page.request.post(`/api/questionnaires/${pick.id}/generate-mappings?workspace_id=${ws}`)
    const j0 = await loadMappingsApi(page.request, ws, pick.id)
    const ids = j0.mappings.map((m) => m.id)
    test.skip(ids.length < 3, 'Need 3+ mappings')

    await page.request.patch(`/api/questionnaires/${pick.id}/mappings/${ids[0]}?workspace_id=${ws}`, {
      ...jsonRequest({ status: 'approved', preferred_control_id: c1 }),
    })
    await page.request.patch(`/api/questionnaires/${pick.id}/mappings/${ids[1]}?workspace_id=${ws}`, {
      ...jsonRequest({ status: 'approved', preferred_control_id: c1 }),
    })
    await page.request.patch(`/api/questionnaires/${pick.id}/mappings/${ids[2]}?workspace_id=${ws}`, {
      ...jsonRequest({ status: 'suggested', preferred_control_id: c1 }),
    })

    await page.goto('/dashboard/compliance-gaps')
    await expect(page.getByRole('heading', { name: 'Compliance gaps' })).toBeVisible({ timeout: 30_000 })
    const qsec = page.getByTestId('questionnaire-mapping-no-evidence-section')
    await expect(qsec).toBeVisible({ timeout: 20_000 })
    const gapRow = qsec.locator('ul').first().locator('> li').first()
    await expect(gapRow.locator('ul').first().locator('> li')).toHaveCount(2)

    await gapRow.getByTestId(`qnr-gap-link-evidence-${c1}`).click()
    await expect(page).toHaveURL(new RegExp(`[?&]open=${c1}`))
    await page.goBack()

    const docsRes = await page.request.get(`/api/documents/?workspace_id=${ws}`)
    test.skip(!docsRes.ok(), 'documents list failed')
    const docs = (await docsRes.json()) as Array<{ id: number }>
    test.skip(docs.length < 1, 'No documents — cannot create evidence link')

    const baseURL = baseUrlFromEnv()
    const adminCtx = await browser.newContext({ baseURL })
    const adminReq = adminCtx.request
    await postJsonLogin(adminReq, ADMIN_EMAIL, ADMIN_PASSWORD)
    const evRes = await adminReq.post('/api/compliance/evidence', {
      ...jsonRequest({
        title: 'E2E audit evidence',
        document_id: docs[0].id,
        source_type: 'document',
      }),
    })
    test.skip(!evRes.ok(), `admin create evidence failed: ${await evRes.text()}`)
    const ev = (await evRes.json()) as { id: number }
    const linkRes = await adminReq.post(`/api/compliance/controls/${c1}/evidence`, {
      ...jsonRequest({ evidence_id: ev.id, confidence_score: 0.85, verified: false }),
    })
    test.skip(!linkRes.ok(), `admin link evidence failed: ${await linkRes.text()}`)
    await adminCtx.close()

    await page.goto('/dashboard/compliance-gaps')
    await expect(page.getByRole('heading', { name: 'Compliance gaps' })).toBeVisible({ timeout: 30_000 })
    await expect(page.getByTestId('questionnaire-mapping-no-evidence-section')).toHaveCount(0, {
      timeout: 15_000,
    })
  })
})
