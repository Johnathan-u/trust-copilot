import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const recommendation = {
  title: 'Quarterly access review recommendation',
  improves_questions: 3,
  evidence_ids: [71],
  control_ids: [41],
  question_ids: [31],
  question_sources: [{ question_id: 31, questionnaire_id: 21 }],
}
const questionnaire = {
  id: 21,
  filename: 'Source questionnaire',
  document_id: null,
  status: 'parsed',
  parse_metadata: null,
  questions: [
    {
      id: 31,
      text: 'How do you review access?',
      section: 'Access management',
      answer_type: null,
    },
  ],
}
const coverage = {
  kpi: {
    total_questions: 4,
    total_answered: 2,
    total_drafted: 1,
    total_insufficient: 1,
    coverage_pct: 25,
    high_confidence_pct: 0,
    insufficient_pct: 25,
    blind_spot_count: 1,
  },
  framework_coverage: [
    {
      framework: 'Internal policy',
      total: 2,
      drafted: 1,
      insufficient: 1,
      coverage_pct: 50,
    },
  ],
  blind_spots: [
    { subject: 'Access management', insufficient_count: 1, total: 2 },
  ],
  weak_areas: [],
  evidence_strength: [],
  recommended_evidence: [recommendation],
  trends: [],
  drill_down: [],
  control_coverage: {
    schema_version: 'compliance-coverage-controls/v1',
    numerator: 0,
    denominator: 1,
    coverage_pct: 0,
    qualified_control_ids: [],
    explanations: [
      {
        control_id: 41,
        state: 'stale',
        rule: 'expired',
        effect: 'excluded_from_numerator',
        denominator_changed: false,
        framework_id: null,
      },
    ],
  },
}
const gap = {
  schema_version: 'evidence-gap-ownership/v1',
  id: 91,
  workspace_id: 7,
  questionnaire_id: 21,
  question_id: 31,
  answer_id: null,
  gap_type: 'missing_evidence',
  reason: 'Current access review evidence is missing.',
  proposed_policy_addition: null,
  suggested_evidence_doc_title: 'Access review record',
  confidence: null,
  status: 'open',
  created_at: '2026-10-01T10:00:00Z',
  updated_at: null,
  closed_at: null,
  close_reason: null,
  control_id: null,
  evaluation_state: 'stale',
  rule_code: 'expired',
  evidence_ids: [],
  next_action: 'refresh_evidence',
  age_days: 28,
  owner_user_id: null,
  owner_missing: true,
  priority: 'high',
  duplicate: { key: null, open_ids: [91], canonical_id: 91, duplicate: false },
}
const evidence = {
  id: 71,
  workspace_id: 7,
  title: 'Quarterly access review',
  source_type: 'document',
  approval_status: 'approved',
  document_id: 51,
  created_at: '2026-10-29T12:00:00Z',
}
const evidencePage = (items = [evidence]) => ({
  total: items.length,
  offset: 0,
  limit: 25,
  items,
})
const closedGap = (status: string) => ({
  ...gap,
  status,
  priority: 'settled',
  ...(status === 'resolved' ? { resolved: true, notified: true } : {}),
})
async function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}
async function installApi(page: Page, role = 'reviewer') {
  const calls: Array<{ path: string; method: string }> = []
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.route('**/api/**', async (route) => {
    const p = new URL(route.request().url()).pathname
    calls.push({ path: p, method: route.request().method() })
    if (p === '/api/auth/me')
      return json(route, {
        id: 42,
        email: 'reviewer@example.com',
        display_name: 'Avery Reviewer',
        workspace_id: 7,
        workspace_name: 'Synthetic workspace',
        workspace_slug: 'synthetic',
        role,
        workspaces: [
          { id: 7, name: 'Synthetic workspace', slug: 'synthetic', role },
          { id: 8, name: 'Second workspace', slug: 'second', role },
        ],
        permissions: {
          can_admin: role === 'admin',
          can_review: role !== 'viewer',
          can_edit: role === 'admin',
          can_export: role === 'admin',
        },
        needs_onboarding: false,
        subscription: { status: 'trialing', plan: 'synthetic' },
        mfa_enrolled: true,
        mfa_required_for_workspace: false,
        workspace_auth_policy: {
          mfa_required: false,
          session_max_age_seconds: null,
        },
      })
    if (p === '/api/compliance-coverage') return json(route, coverage)
    if (p === '/api/evidence-gaps')
      return json(route, {
        schema_version: 'evidence-gap-ownership/v1',
        gaps: [gap],
      })
    if (p === '/api/evidence-search') return json(route, evidencePage())
    if (p === '/api/compliance/evidence/71') return json(route, evidence)
    if (p === '/api/questionnaires/21') return json(route, questionnaire)
    if (p === '/api/documents') return json(route, [])
    if (p.includes('unread-count')) return json(route, { count: 0 })
    if (p.includes('/auth/alerts')) return json(route, { alerts: [] })
    return json(route, {})
  })
  return calls
}

test('reviewer sees resolution, ownership and source links without administrator decisions or automatic writes', async ({
  page,
}) => {
  const calls = await installApi(page)
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByRole('heading', { name: 'Evidence gaps', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Unassigned', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('link', { name: 'Review questionnaire' })
  ).toHaveAttribute('href', '/dashboard/questionnaires/21')
  await expect(
    page.getByText(/Questionnaire coverage is not certification/)
  ).toBeVisible()
  await expect(page.locator('#main-content')).not.toContainText('Control 41')
  await expect(
    page.getByRole('button', { name: /Dismiss|Accept gap/ })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Resolve gap', exact: true })
  ).toBeVisible()
  expect(
    calls.filter(
      (call) =>
        call.path.startsWith('/api/evidence-gaps') && call.method !== 'GET'
    )
  ).toEqual([])
})

test('schema mismatch is an error, then retry recovers without stale failure', async ({
  page,
}) => {
  await installApi(page)
  let malformed = true
  await page.route('**/api/evidence-gaps', (route) =>
    json(
      route,
      malformed
        ? { schema_version: 'unexpected', gaps: [] }
        : { schema_version: 'evidence-gap-ownership/v1', gaps: [] }
    )
  )
  await page.goto('/dashboard/compliance-gaps')
  const region = page.getByRole('region', {
    name: 'Evidence gaps',
    exact: true,
  })
  await expect(region.locator('[data-state="error"]')).toBeVisible()
  await expect(
    region.getByText('No evidence gaps', { exact: true })
  ).toHaveCount(0)
  malformed = false
  await region.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(
    region.getByText('No evidence gaps', { exact: true })
  ).toBeVisible()
  await expect(region.locator('[data-state="error"]')).toHaveCount(0)
})

test('filters and permitted export reflect the displayed snapshot', async ({
  page,
}) => {
  await installApi(page, 'admin')
  await page.route('**/api/evidence-gaps', (route) =>
    json(route, {
      schema_version: 'evidence-gap-ownership/v1',
      gaps: [
        gap,
        {
          ...gap,
          id: 92,
          status: 'resolved',
          priority: 'settled',
          suggested_evidence_doc_title: 'Historic record',
        },
      ],
    })
  )
  await page.goto('/dashboard/compliance-gaps')
  await page.getByLabel('Gap status', { exact: true }).selectOption('resolved')
  await expect(page.getByText('Historic record', { exact: true })).toBeVisible()
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toHaveCount(0)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export displayed gaps' }).click()
  await expect((await download).suggestedFilename()).toBe('evidence-gaps.csv')
})

test('viewer receives denial without fetching private gap data', async ({
  page,
}) => {
  const calls = await installApi(page, 'viewer')
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByRole('heading', { name: 'This section is not available' })
  ).toBeVisible()
  expect(calls.filter((call) => call.path === '/api/evidence-gaps')).toEqual([])
  expect(
    calls.filter(
      (call) =>
        call.path === '/api/compliance-coverage' ||
        call.path.startsWith('/api/compliance/evidence/') ||
        call.path.startsWith('/api/questionnaires/')
    )
  ).toEqual([])
})

test('recommendations disclose real evidence and matching questions on demand without writes', async ({
  page,
}) => {
  const calls = await installApi(page)
  await page.goto('/dashboard/compliance-gaps')
  const recommendations = page.getByRole('region', {
    name: 'Recommended Next Evidence',
  })
  await expect(recommendations.getByText(recommendation.title)).toBeVisible()
  expect(
    calls.filter(
      (call) =>
        call.path.startsWith('/api/compliance/evidence/') ||
        call.path.startsWith('/api/questionnaires/')
    )
  ).toEqual([])
  await expect(
    recommendations.getByRole('link', { name: 'View control 41' })
  ).toHaveAttribute('href', '/dashboard/controls/41')
  await recommendations
    .getByRole('button', { name: 'View evidence 71' })
    .click()
  await expect(
    recommendations.getByText('Quarterly access review', { exact: true })
  ).toBeVisible()
  await recommendations
    .getByRole('button', { name: 'View question 31' })
    .click()
  await expect(
    recommendations.getByText(questionnaire.questions[0].text)
  ).toBeVisible()
  await expect(
    recommendations.getByText(/Reported suggestion count:/)
  ).toContainText('3')
  const questionnaireLink = recommendations.getByRole('link', {
    name: 'Open source questionnaire',
  })
  await expect(questionnaireLink).toHaveAttribute(
    'href',
    '/dashboard/questionnaires/21'
  )
  expect(calls.filter((call) => call.method !== 'GET')).toEqual([])
  await questionnaireLink.click()
  await expect(page).toHaveURL(/\/dashboard\/questionnaires\/21$/)
  await expect(page.getByText(questionnaire.questions[0].text)).toBeVisible()
})

test('legacy and empty provenance stay visible without invented source links', async ({
  page,
}) => {
  const calls = await installApi(page)
  await page.route('**/api/compliance-coverage', (route) =>
    json(route, {
      ...coverage,
      kpi: { ...coverage.kpi, total_questions: 0 },
      recommended_evidence: [
        {
          title: 'No live sources',
          improves_questions: 7,
          evidence_ids: [],
          control_ids: [],
          question_ids: [],
          question_sources: [],
        },
        {
          title: 'Legacy question source',
          improves_questions: 2,
          question_ids: [31],
        },
      ],
    })
  )
  await page.goto('/dashboard/compliance-gaps')
  const recommendations = page.getByRole('region', {
    name: 'Recommended Next Evidence',
  })
  await expect(recommendations.getByText('No live sources')).toBeVisible()
  await expect(
    recommendations.getByText(
      'Source detail is unavailable for this recommendation.'
    )
  ).toBeVisible()
  await expect(
    recommendations.getByText(/Question sources without detail: 1/)
  ).toBeVisible()
  await expect(recommendations.getByRole('link')).toHaveCount(0)
  await expect(recommendations.getByRole('button')).toHaveCount(0)
  expect(
    calls.filter(
      (call) =>
        call.path.startsWith('/api/compliance/evidence/') ||
        call.path.startsWith('/api/questionnaires/')
    )
  ).toEqual([])
})

test('malformed recommendation provenance fails the coverage read and retry recovers', async ({
  page,
}) => {
  await installApi(page)
  let malformed = true
  await page.route('**/api/compliance-coverage', (route) =>
    json(route, {
      ...coverage,
      recommended_evidence: [
        { ...recommendation, control_ids: malformed ? ['../other'] : [41] },
      ],
    })
  )
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  const error = page.locator('#main-content [data-state="error"]')
  await expect(error).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Recommended Next Evidence' })
  ).toHaveCount(0)
  malformed = false
  await error.getByRole('button', { name: 'Try again' }).click()
  await expect(
    page.getByRole('link', { name: 'View control 41' })
  ).toBeVisible()
  await expect(error).toHaveCount(0)
})

for (const failure of [
  'forbidden',
  'missing',
  'foreign',
  'mismatched-question',
] as const) {
  test(`source detail rejects ${failure} and can retry without exposing unverified data`, async ({
    page,
  }) => {
    await installApi(page)
    let broken = true
    const question = failure === 'mismatched-question'
    await page.route(
      question ? '**/api/questionnaires/21?*' : '**/api/compliance/evidence/71',
      (route) => {
        if (!broken) return json(route, question ? questionnaire : evidence)
        if (failure === 'forbidden' || failure === 'missing')
          return json(
            route,
            { detail: 'Private failure content' },
            failure === 'forbidden' ? 403 : 404
          )
        return json(
          route,
          question
            ? {
                ...questionnaire,
                questions: [
                  {
                    ...questionnaire.questions[0],
                    id: 32,
                    text: 'Private question content',
                  },
                ],
              }
            : {
                ...evidence,
                workspace_id: 8,
                title: 'Private foreign evidence',
              }
        )
      }
    )
    await page.goto('/dashboard/compliance-gaps')
    const recommendations = page.getByRole('region', {
      name: 'Recommended Next Evidence',
    })
    await recommendations
      .getByRole('button', {
        name: question ? 'View question 31' : 'View evidence 71',
      })
      .click()
    await expect(
      recommendations.getByText(
        question
          ? 'Question source unavailable.'
          : 'Evidence source unavailable.'
      )
    ).toBeVisible()
    await expect(recommendations).not.toContainText('Private')
    await expect(
      recommendations.getByRole('link', { name: 'Open source questionnaire' })
    ).toHaveCount(0)
    broken = false
    await recommendations.getByRole('button', { name: 'Try again' }).click()
    await expect(
      recommendations.getByText(
        question ? questionnaire.questions[0].text : evidence.title,
        { exact: true }
      )
    ).toBeVisible()
    await expect(recommendations.locator('[data-state="error"]')).toHaveCount(0)
  })
}

test('background polling pauses while hidden and failures retain a labelled snapshot', async ({
  page,
}) => {
  await installApi(page)
  let requests = 0
  let fail = false
  await page.route('**/api/evidence-gaps', (route) => {
    requests++
    return fail
      ? json(route, {}, 500)
      : json(route, {
          schema_version: 'evidence-gap-ownership/v1',
          gaps: [gap],
        })
  })
  await page.clock.install()
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  const before = requests
  await page.clock.fastForward(120000)
  expect(requests).toBe(before)
  fail = true
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  const region = page.getByRole('region', {
    name: 'Evidence gaps',
    exact: true,
  })
  await expect(
    region.getByText('Showing saved snapshot: refresh failed.', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
})

for (const width of [360, 768, 1440]) {
  test(`gap report is accessible and contained at ${width}px`, async ({
    page,
  }, testInfo) => {
    await installApi(page)
    const longTitle = 'Long evidence label '.repeat(16)
    const longSubject = 'AccessManagement'.repeat(14)
    await page.route('**/api/evidence-gaps', (route) =>
      json(route, {
        schema_version: 'evidence-gap-ownership/v1',
        gaps: [
          gap,
          {
            ...gap,
            id: 93,
            suggested_evidence_doc_title: longTitle,
            reason: 'Long reason '.repeat(30),
          },
        ],
      })
    )
    await page.route('**/api/compliance-coverage', (route) =>
      json(route, {
        ...coverage,
        framework_coverage: [
          { ...coverage.framework_coverage[0], framework: longSubject },
        ],
        recommended_evidence: [{ ...recommendation, title: longTitle }],
      })
    )
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/dashboard/compliance-gaps')
    await expect(
      page.getByText('Access review record', { exact: true })
    ).toBeVisible()
    await page.getByLabel('Gap status', { exact: true }).focus()
    await expect(page.getByLabel('Gap status', { exact: true })).toBeFocused()
    await page.keyboard.press('Tab')
    await page.getByText('View chart data', { exact: true }).first().click()
    await expect(
      page.getByRole('rowheader', { name: longSubject, exact: true })
    ).toBeVisible()
    const recommendationRegion = page.getByRole('region', {
      name: 'Recommended Next Evidence',
    })
    await recommendationRegion
      .getByRole('button', { name: 'View evidence 71' })
      .focus()
    await page.keyboard.press('Enter')
    await expect(
      recommendationRegion.getByRole('button', { name: 'Hide evidence 71' })
    ).toBeFocused()
    await expect(
      recommendationRegion.getByText('Quarterly access review', { exact: true })
    ).toBeVisible()
    await recommendationRegion
      .getByRole('button', { name: 'View question 31' })
      .focus()
    await page.keyboard.press('Enter')
    await expect(
      recommendationRegion.getByText(questionnaire.questions[0].text)
    ).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(
      recommendationRegion.getByRole('link', {
        name: 'Open source questionnaire',
      })
    ).toBeFocused()
    const main = page.locator('#main-content')
    expect(await main.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
      true
    )
    await expect(
      main.locator('[aria-hidden="true"] svg[tabindex="0"]')
    ).toHaveCount(0)
    const result = await new AxeBuilder({ page })
      .include('#main-content')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const violations = result.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    const evidenceDir = path.resolve('../../artifacts/acceptance/TC-15-025')
    mkdirSync(path.join(evidenceDir, 'screenshots'), { recursive: true })
    writeFileSync(
      path.join(evidenceDir, `axe-${width}.json`),
      JSON.stringify({ width, violations }, null, 2)
    )
    expect(
      violations.filter((item) =>
        ['critical', 'serious'].includes(item.impact || '')
      )
    ).toEqual([])
    await page.screenshot({
      path: path.join(evidenceDir, 'screenshots', `gaps-${width}.png`),
      fullPage: true,
    })
    await testInfo.attach(`gaps-${width}`, {
      path: path.join(evidenceDir, 'screenshots', `gaps-${width}.png`),
      contentType: 'image/png',
    })
    await testInfo.attach(`axe-${width}`, {
      path: path.join(evidenceDir, `axe-${width}.json`),
      contentType: 'application/json',
    })
    const resolveButton = page
      .getByRole('button', { name: 'Resolve gap', exact: true })
      .first()
    await resolveButton.click()
    const dialog = page.getByRole('dialog')
    await expect(
      dialog.getByRole('radio', { name: /Quarterly access review/ })
    ).toBeVisible()
    await expect(
      dialog.getByRole('button', { name: 'Cancel', exact: true })
    ).toBeFocused()
    await page.keyboard.press('Tab')
    expect(
      await dialog.evaluate((element) =>
        element.contains(document.activeElement)
      )
    ).toBe(true)
    expect(
      await dialog.evaluate(
        (element) => element.scrollWidth <= element.clientWidth
      )
    ).toBe(true)
    const actionAudit = await new AxeBuilder({ page })
      .include('[role="dialog"]')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const actionViolations = actionAudit.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    expect(
      actionViolations.filter((item) =>
        ['critical', 'serious'].includes(item.impact || '')
      )
    ).toEqual([])
    const actionAxePath = path.join(evidenceDir, `axe-actions-${width}.json`)
    writeFileSync(
      actionAxePath,
      JSON.stringify({ width, violations: actionViolations }, null, 2)
    )
    await testInfo.attach(`axe-actions-${width}`, {
      path: actionAxePath,
      contentType: 'application/json',
    })
    const actionScreenshot = path.join(
      evidenceDir,
      'screenshots',
      `gap-actions-${width}.png`
    )
    await page.screenshot({ path: actionScreenshot, fullPage: true })
    await testInfo.attach(`gap-actions-${width}`, {
      path: actionScreenshot,
      contentType: 'image/png',
    })
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(resolveButton).toBeFocused()
  })
}

test('changing workspace clears the previous snapshot before the new read completes', async ({
  page,
}) => {
  await installApi(page, 'admin')
  let changed = false
  let release: () => void = () => {}
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/auth/switch-workspace', (route) => {
    changed = true
    return json(route, {
      workspace_id: 8,
      workspace_name: 'Second workspace',
      workspace_slug: 'second',
      role: 'admin',
    })
  })
  await page.route('**/api/evidence-gaps', async (route) => {
    if (!changed) return route.fallback()
    await pending
    return json(route, {
      schema_version: 'evidence-gap-ownership/v1',
      gaps: [],
    })
  })
  await page.route('**/api/compliance-coverage', async (route) => {
    if (!changed) return route.fallback()
    await pending
    return json(route, { ...coverage, recommended_evidence: [] })
  })
  await page.route('**/api/questionnaires/21?*', async (route) => {
    await pending
    return json(route, questionnaire)
  })
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'View evidence 71' }).click()
  await expect(
    page.getByText('Quarterly access review', { exact: true })
  ).toBeVisible()
  await page.getByRole('button', { name: 'View question 31' }).click()
  await expect(
    page.getByText('Loading question source', { exact: true })
  ).toBeVisible()
  await page.getByLabel('Workspace', { exact: true }).selectOption('8')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByText('Quarterly access review', { exact: true })
  ).toHaveCount(0)
  release()
  await expect(
    page.getByText('No evidence gaps', { exact: true })
  ).toBeVisible()
  await expect(page.getByText(questionnaire.questions[0].text)).toHaveCount(0)
  await expect(
    page.getByRole('link', { name: 'Open source questionnaire' })
  ).toHaveCount(0)
})

test('coverage failure and empty questionnaire data do not hide the gap list', async ({
  page,
}) => {
  await installApi(page)
  let broken = true
  await page.route('**/api/compliance-coverage', (route) =>
    json(
      route,
      broken
        ? { ...coverage, framework_coverage: null }
        : { ...coverage, kpi: { ...coverage.kpi, total_questions: 0 } }
    )
  )
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await expect(page.locator('#main-content [data-state="error"]')).toBeVisible()
  broken = false
  await page
    .locator('#main-content [data-state="error"]')
    .getByRole('button', { name: 'Try again' })
    .click()
  await expect(page.getByText(/No questionnaire data yet/)).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Control denominator' })
  ).toBeVisible()
  await expect(
    page.getByText('0 qualified of 1 applicable', { exact: true })
  ).toBeVisible()
  await expect(page.locator('#main-content [data-state="error"]')).toHaveCount(
    0
  )
})

test('retained answer revisions are labelled as record ratios, including values above 100 percent', async ({
  page,
}) => {
  await installApi(page)
  await page.route('**/api/compliance-coverage', (route) =>
    json(route, {
      ...coverage,
      kpi: {
        ...coverage.kpi,
        total_questions: 1,
        total_drafted: 2,
        total_insufficient: 3,
        coverage_pct: 200,
        insufficient_pct: 300,
      },
      recommended_evidence: [
        { title: 'Review access logs', improves_questions: 2 },
      ],
    })
  )
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('2 draft answer records / 1 questions', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('3 insufficient answer records / 1 questions', {
      exact: true,
    })
  ).toBeVisible()
  await expect(
    page.getByText(/Retained revisions can make these ratios exceed 100%/)
  ).toBeVisible()
  await expect(page.getByText(/Reported suggestion count:/)).toContainText('2')
  await expect(
    page.getByText('Source detail is unavailable for this recommendation.')
  ).toBeVisible()
})

for (const decision of ['accepted', 'dismissed'] as const) {
  test(`administrator confirms ${decision} only after server acknowledgment`, async ({
    page,
  }) => {
    await installApi(page, 'admin')
    let current = { ...gap }
    let sent = false
    let release: () => void = () => {}
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    await page.route('**/api/evidence-gaps', (route) =>
      json(route, {
        schema_version: 'evidence-gap-ownership/v1',
        gaps: [current],
      })
    )
    await page.route('**/api/evidence-gaps/91/decision', async (route) => {
      expect(route.request().postDataJSON()).toEqual({ status: decision })
      expect(route.request().headers()['idempotency-key']).toBeTruthy()
      sent = true
      await held
      current = closedGap(decision)
      await json(route, current)
    })
    await page.goto('/dashboard/compliance-gaps')
    const trigger = page.getByRole('button', {
      name: decision === 'accepted' ? 'Accept gap' : 'Dismiss gap',
      exact: true,
    })
    await trigger.click()
    let dialog = page.getByRole('dialog')
    await expect(
      dialog.getByRole('button', { name: 'Cancel', exact: true })
    ).toBeFocused()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(trigger).toBeFocused()
    expect(sent).toBe(false)
    await trigger.click()
    dialog = page.getByRole('dialog')
    await dialog
      .getByRole('button', {
        name: decision === 'accepted' ? 'Confirm accept' : 'Confirm dismiss',
      })
      .click()
    try {
      await expect.poll(() => sent).toBe(true)
      await expect(
        dialog.getByRole('button', { name: 'Saving…' })
      ).toBeDisabled()
      await expect(
        page
          .locator('li')
          .filter({
            has: page
              .locator('h3')
              .filter({ hasText: /^Access review record$/ }),
          })
          .getByText('Open', { exact: true })
      ).toBeVisible()
    } finally {
      release()
    }
    await expect(dialog).toHaveCount(0)
    await expect(
      page.getByText(`Access review record: ${decision} confirmed.`, {
        exact: true,
      })
    ).toBeVisible()
    await page.reload()
    await expect(
      page
        .locator('li')
        .filter({
          has: page.locator('h3').filter({ hasText: /^Access review record$/ }),
        })
        .getByText(decision === 'accepted' ? 'Accepted' : 'Dismissed', {
          exact: true,
        })
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Resolve gap', exact: true })
    ).toHaveCount(0)
  })
}

for (const status of [403, 404, 409]) {
  test(`rejected gap decision (${status}) preserves the open row without a success notice`, async ({
    page,
  }) => {
    await installApi(page, 'admin')
    await page.route('**/api/evidence-gaps/91/decision', (route) =>
      json(route, { detail: 'private_backend_detail' }, status)
    )
    await page.goto('/dashboard/compliance-gaps')
    await page.getByRole('button', { name: 'Accept gap', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Confirm accept' }).click()
    await expect(dialog.getByRole('alert')).toContainText(
      status === 403
        ? 'permission'
        : status === 404
          ? 'no longer available'
          : 'changed'
    )
    await expect(dialog).not.toContainText('private_backend_detail')
    await expect(page.getByText(/accepted confirmed/)).toHaveCount(0)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    if (status === 409) {
      await page.route('**/api/evidence-gaps', (route) =>
        json(route, {
          schema_version: 'evidence-gap-ownership/v1',
          gaps: [closedGap('dismissed')],
        })
      )
      await page
        .getByRole('button', { name: 'Refresh gaps', exact: true })
        .click()
      await expect(
        page.getByRole('button', { name: 'Accept gap', exact: true })
      ).toHaveCount(0)
      await expect(
        page
          .locator('li')
          .filter({
            has: page
              .locator('h3')
              .filter({ hasText: /^Access review record$/ }),
          })
          .getByText('Dismissed', { exact: true })
      ).toBeVisible()
    } else
      await expect(
        page.getByRole('button', { name: 'Accept gap', exact: true })
      ).toBeVisible()
  })
}

test('reviewer keeps a rejected evidence choice and uses a new request key when selecting different evidence', async ({
  page,
}) => {
  await installApi(page)
  await page.route('**/api/evidence-search?*', (route) =>
    json(
      route,
      evidencePage([
        evidence,
        { ...evidence, id: 72, title: 'Updated access review' },
      ])
    )
  )
  const writes: Array<{ body: unknown; key: string }> = []
  let current = { ...gap }
  await page.route('**/api/evidence-gaps', (route) =>
    json(route, {
      schema_version: 'evidence-gap-ownership/v1',
      gaps: [current],
    })
  )
  await page.route('**/api/evidence-gaps/91/resolve', (route) => {
    writes.push({
      body: route.request().postDataJSON(),
      key: route.request().headers()['idempotency-key'],
    })
    if (writes.length === 1)
      return json(
        route,
        { detail: { rule: 'evidence_expired', resolved: false } },
        400
      )
    current = closedGap('resolved')
    return json(route, current)
  })
  await page.goto('/dashboard/compliance-gaps')
  await page.getByRole('button', { name: 'Resolve gap', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('radio', { name: /Quarterly access review/ }).check()
  await dialog
    .getByRole('button', { name: 'Resolve with selected evidence' })
    .click()
  await expect(dialog.getByRole('alert')).toContainText(
    'approved, current evidence'
  )
  await expect(
    dialog.getByRole('radio', { name: /Quarterly access review/ })
  ).toBeChecked()
  await expect(dialog).not.toContainText('evidence_expired')
  await dialog.getByRole('radio', { name: /Updated access review/ }).check()
  await dialog
    .getByRole('button', { name: 'Resolve with selected evidence' })
    .click()
  await expect(
    page.getByText('Access review record: resolved confirmed.', { exact: true })
  ).toBeVisible()
  expect(writes.map((item) => item.body)).toEqual([
    { evidence_id: 71 },
    { evidence_id: 72 },
  ])
  expect(writes[0].key).not.toBe(writes[1].key)
})

test('lost resolution response retries the same intent safely and reports notification failure independently', async ({
  page,
}) => {
  await installApi(page)
  const keys: string[] = []
  let confirmed = false
  await page.route('**/api/evidence-gaps', (route) =>
    confirmed
      ? json(route, {}, 500)
      : json(route, {
          schema_version: 'evidence-gap-ownership/v1',
          gaps: [gap],
        })
  )
  await page.route('**/api/evidence-gaps/91/resolve', (route) => {
    keys.push(route.request().headers()['idempotency-key'])
    if (keys.length === 1) return route.abort('failed')
    confirmed = true
    return json(route, {
      ...closedGap('resolved'),
      notified: false,
      notification_error: 'delivery_failed',
    })
  })
  await page.goto('/dashboard/compliance-gaps')
  await page.getByRole('button', { name: 'Resolve gap', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('radio', { name: /Quarterly access review/ }).check()
  await dialog
    .getByRole('button', { name: 'Resolve with selected evidence' })
    .click()
  await expect(dialog.getByRole('alert')).toContainText('Could not confirm')
  await expect(
    dialog.getByRole('radio', { name: /Quarterly access review/ })
  ).toBeChecked()
  await dialog
    .getByRole('button', { name: 'Resolve with selected evidence' })
    .click()
  await expect(
    page.getByText(/resolved confirmed.*notification delivery failed/)
  ).toBeVisible()
  await expect(
    page.getByText('Showing saved snapshot: refresh failed.', { exact: true })
  ).toBeVisible()
  await expect(
    page
      .locator('li')
      .filter({
        has: page.getByRole('heading', {
          name: 'Access review record',
          exact: true,
        }),
      })
      .getByText('Resolved', { exact: true })
  ).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
})

test('malformed successful response never becomes a confirmed decision', async ({
  page,
}) => {
  await installApi(page, 'admin')
  await page.route('**/api/evidence-gaps/91/decision', (route) =>
    json(route, { ...closedGap('accepted'), id: 999 })
  )
  await page.goto('/dashboard/compliance-gaps')
  await page.getByRole('button', { name: 'Accept gap', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Confirm accept' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Could not confirm')
  await expect(page.getByText(/accepted confirmed/)).toHaveCount(0)
})

test('evidence choices recover from failure and empty results, and support bounded search and paging', async ({
  page,
}) => {
  await installApi(page, 'editor')
  let failSearch = true
  await page.route('**/api/evidence-search?*', (route) => {
    const params = new URL(route.request().url()).searchParams
    expect(params.get('approval_status')).toBe('approved')
    expect(params.get('limit')).toBe('25')
    if (failSearch) return json(route, {}, 500)
    if (!params.get('title_query')) return json(route, evidencePage([]))
    const offset = Number(params.get('offset'))
    return json(route, {
      total: 26,
      offset,
      limit: 25,
      items: [
        {
          ...evidence,
          title:
            offset === 0 ? 'First matching review' : 'Last matching review',
        },
      ],
    })
  })
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByRole('button', { name: 'Accept gap', exact: true })
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Resolve gap', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(
    dialog.getByRole('button', { name: 'Try again', exact: true })
  ).toBeVisible()
  failSearch = false
  await dialog.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(
    dialog.getByText('No approved evidence matches this search.', {
      exact: true,
    })
  ).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Resolve with selected evidence' })
  ).toBeDisabled()
  await dialog
    .getByLabel('Search evidence titles', { exact: true })
    .fill('matching')
  await dialog
    .getByRole('button', { name: 'Search evidence', exact: true })
    .click()
  await expect(
    dialog.getByRole('radio', { name: /First matching review/ })
  ).toBeVisible()
  await dialog
    .getByRole('button', { name: 'Next evidence', exact: true })
    .click()
  await expect(
    dialog.getByRole('radio', { name: /Last matching review/ })
  ).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Next evidence', exact: true })
  ).toBeDisabled()
})

test('closing the resolver and changing workspace ignores an old evidence response', async ({
  page,
}) => {
  await installApi(page, 'admin')
  let changed = false
  let requested = false
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/evidence-search?*', async (route) => {
    requested = true
    await held
    await json(route, evidencePage())
  })
  await page.route('**/api/auth/switch-workspace', (route) => {
    changed = true
    return json(route, {
      workspace_id: 8,
      workspace_name: 'Second workspace',
      workspace_slug: 'second',
      role: 'admin',
    })
  })
  await page.route('**/api/evidence-gaps', (route) =>
    json(route, {
      schema_version: 'evidence-gap-ownership/v1',
      gaps: changed ? [] : [gap],
    })
  )
  await page.goto('/dashboard/compliance-gaps')
  await page.getByRole('button', { name: 'Resolve gap', exact: true }).click()
  try {
    await expect.poll(() => requested).toBe(true)
    await page
      .getByRole('dialog')
      .getByRole('button', { name: 'Cancel', exact: true })
      .click()
    await page.getByLabel('Workspace', { exact: true }).selectOption('8')
    await expect(
      page.getByText('No evidence gaps', { exact: true })
    ).toBeVisible()
  } finally {
    release()
  }
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText(/Quarterly access review/)).toHaveCount(0)
  await expect(page.getByText(/resolved confirmed/)).toHaveCount(0)
})

test('permission revocation clears a confirmed private gap title and action state', async ({
  page,
}) => {
  await installApi(page, 'admin')
  let denied = false
  let current = { ...gap }
  await page.route('**/api/evidence-gaps', (route) =>
    denied
      ? json(route, {}, 403)
      : json(route, {
          schema_version: 'evidence-gap-ownership/v1',
          gaps: [current],
        })
  )
  await page.route('**/api/evidence-gaps/91/decision', (route) => {
    current = closedGap('accepted')
    return json(route, current)
  })
  await page.goto('/dashboard/compliance-gaps')
  await page.getByRole('button', { name: 'Accept gap', exact: true }).click()
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Confirm accept' })
    .click()
  await expect(
    page.getByText('Access review record: accepted confirmed.', { exact: true })
  ).toBeFocused()
  denied = true
  await page.getByRole('button', { name: 'Refresh gaps', exact: true }).click()
  const region = page.getByRole('region', {
    name: 'Evidence gaps',
    exact: true,
  })
  await expect(region.locator('[data-state="error"]')).toBeVisible()
  await expect(region).not.toContainText('Access review record')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  denied = false
  await region.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(
    region.getByRole('heading', { name: 'Access review record', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Access review record: accepted confirmed.', { exact: true })
  ).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
})
