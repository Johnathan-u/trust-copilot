import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

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
  recommended_evidence: [],
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
    if (p.includes('unread-count')) return json(route, { count: 0 })
    if (p.includes('/auth/alerts')) return json(route, { alerts: [] })
    return json(route, {})
  })
  return calls
}

test('read-only gaps show ownership and source links without internal ids or writes', async ({
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
    page.getByRole('button', { name: /Resolve|Dismiss|Accept gap/ })
  ).toHaveCount(0)
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
})

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
  await page.goto('/dashboard/compliance-gaps')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await page.getByLabel('Workspace', { exact: true }).selectOption('8')
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toHaveCount(0)
  release()
  await expect(
    page.getByText('No evidence gaps', { exact: true })
  ).toBeVisible()
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
