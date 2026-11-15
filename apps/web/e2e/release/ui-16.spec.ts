import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Deterministic control paths for /dashboard/questionnaires. Real API
// qualification stays outside this spec. The list endpoint has no page or
// sort parameters, and it does not report review progress, job progress, or
// an ambiguity flag.
test.use({ storageState: { cookies: [], origins: [] } })
test.describe.configure({ timeout: 90_000 })

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-15-017'
)

type Qnr = {
  id: number
  display_id: string
  filename: string
  status: string
  created_at: string
  deleted_at: string | null
  frameworks: string[]
  subject_areas: string[]
  parse_metadata?: string | null
  question_count?: number
  review_reviewed?: number
  review_total?: number
  mapping_ambiguous?: boolean
  mapping_confirmation_url?: string
}

type RoleName = 'admin' | 'editor' | 'reviewer'

function qnr(overrides: Partial<Qnr> = {}): Qnr {
  return {
    id: 3,
    display_id: 'QNR-3',
    filename: 'Vendor.xlsx',
    status: 'uploaded',
    created_at: '2026-10-01T12:00:00Z',
    deleted_at: null,
    frameworks: ['SOC 2'],
    subject_areas: ['Access Control'],
    ...overrides,
  }
}

const failedParseJob = {
  id: 15,
  kind: 'parse_questionnaire',
  status: 'failed',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:00:00Z',
  started_at: null,
  completed_at: '2026-10-30T12:05:00Z',
  next_attempt_at: null,
  retry_scheduled: false,
  retries_exhausted: true,
  charge_uncertain: false,
  progress: null,
  outcome: null,
  error_code: 'bad_input',
  object_ref: { type: 'questionnaire', id: 3 },
}

const answerProgressJob = {
  id: 16,
  kind: 'generate_answers',
  status: 'running',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:06:00Z',
  started_at: '2026-10-30T12:06:30Z',
  completed_at: null,
  next_attempt_at: null,
  retry_scheduled: false,
  retries_exhausted: false,
  charge_uncertain: false,
  progress: { generated: 4, total: 10 },
  outcome: null,
  object_ref: { type: 'questionnaire', id: 4 },
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function gate() {
  let release!: () => void
  const wait = new Promise<void>((resolve) => {
    release = resolve
  })
  return { wait, release }
}

type Call = { path: string; method: string; search: string }

function hasParam(search: string, key: string, value: string) {
  return new URLSearchParams(search).get(key) === value
}

async function setup(
  page: Page,
  options: {
    role?: RoleName
    qnrs?: Qnr[]
    otherQnrs?: Qnr[]
    jobs?: unknown[]
    listStatus?: number
  } = {}
) {
  const role = options.role ?? 'admin'
  const state = {
    workspace: 7,
    qnrs: options.qnrs ?? [qnr()],
    otherQnrs: options.otherQnrs ?? [
      qnr({
        id: 8,
        display_id: 'QNR-8',
        filename: 'Second.xlsx',
        frameworks: ['HIPAA'],
      }),
    ],
    jobs: options.jobs ?? [],
    listStatus: options.listStatus ?? 200,
    alphaHold: null as Promise<void> | null,
    uploadHold: null as Promise<void> | null,
    metadataHold: null as Promise<void> | null,
    restoreHold: null as Promise<void> | null,
    archiveHold: null as Promise<void> | null,
    retryHold: null as Promise<void> | null,
    uploadStatus: 200,
    metadataStatus: 200,
    restoreStatus: 200,
    archiveStatus: 200,
    jobMode: 'parsed' as 'parsed' | 'failed',
    jobPolls: 0,
    completedProgress: null as { generated: number; total: number } | null,
  }
  const calls: Call[] = []
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathName = url.pathname.replace(/\/$/, '')
    const method = request.method()
    calls.push({ path: pathName, method, search: url.search })
    const me = {
      id: 42,
      email: 'operator@example.com',
      display_name: 'Synthetic Operator',
      workspace_id: state.workspace,
      workspace_name:
        state.workspace === 7 ? 'First workspace' : 'Second workspace',
      workspace_slug: 'synthetic',
      role,
      workspaces: [7, 8].map((id) => ({
        id,
        name: id === 7 ? 'First workspace' : 'Second workspace',
        slug: `synthetic-${id}`,
        role,
      })),
      permissions: {
        can_admin: role === 'admin',
        can_edit: role === 'admin' || role === 'editor',
        can_review: true,
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
    }
    const fulfill = (body: unknown, status = 200) =>
      json(route, body, status).catch(() => {})
    if (pathName === '/api/auth/me') return fulfill(me)
    if (pathName === '/api/auth/switch-workspace') {
      state.workspace = request.postDataJSON().workspace_id
      return fulfill({
        ...me,
        workspace_id: state.workspace,
        workspace_name:
          state.workspace === 7 ? 'First workspace' : 'Second workspace',
        role,
      })
    }
    if (pathName === '/api/questionnaires' && method === 'GET') {
      const search = url.searchParams.get('search') || ''
      if (search === 'alpha' && state.alphaHold) await state.alphaHold
      if (state.listStatus !== 200) {
        return fulfill({ detail: 'Synthetic read failure' }, state.listStatus)
      }
      let rows = state.workspace === 7 ? [...state.qnrs] : [...state.otherQnrs]
      const archived = url.searchParams.get('archived') || 'active'
      rows = rows.filter((row) => {
        if (archived === 'active') return !row.deleted_at
        if (archived === 'only') return Boolean(row.deleted_at)
        return true
      })
      if (search) {
        const needle = search.toLowerCase()
        rows = rows.filter(
          (row) =>
            row.filename.toLowerCase().includes(needle) ||
            row.display_id.toLowerCase().includes(needle)
        )
      }
      const framework = url.searchParams.get('framework')
      if (framework) {
        rows = rows.filter((row) => row.frameworks.includes(framework))
      }
      const subject = url.searchParams.get('subject_area')
      if (subject) {
        rows = rows.filter((row) => row.subject_areas.includes(subject))
      }
      const status = url.searchParams.get('status')
      if (status) rows = rows.filter((row) => row.status === status)
      return fulfill(rows)
    }
    if (pathName === '/api/questionnaires/upload' && method === 'POST') {
      if (state.uploadHold) await state.uploadHold
      if (state.uploadStatus !== 200) {
        return fulfill(
          {
            detail:
              'File must have an allowed extension. Allowed: .docx, .pdf, .xlsx',
          },
          state.uploadStatus
        )
      }
      return fulfill({
        id: 8,
        display_id: 'QNR-8',
        filename: 'synthetic.xlsx',
        status: 'uploaded',
        job_id: 15,
      })
    }
    if (/^\/api\/questionnaires\/\d+\/delete-preview$/.test(pathName)) {
      return fulfill({
        dependencies: { answers: 2, exports: 0 },
        recommended_action: 'archive',
        unmodeled_warning: null,
      })
    }
    if (
      /^\/api\/questionnaires\/\d+\/metadata$/.test(pathName) &&
      method === 'PATCH'
    ) {
      if (state.metadataHold) await state.metadataHold
      if (state.metadataStatus !== 200) {
        return fulfill(
          { detail: 'Synthetic metadata failure' },
          state.metadataStatus
        )
      }
      return fulfill({ ok: true })
    }
    if (
      /^\/api\/questionnaires\/\d+\/restore$/.test(pathName) &&
      method === 'POST'
    ) {
      if (state.restoreHold) await state.restoreHold
      if (state.restoreStatus !== 200) {
        return fulfill(
          { detail: 'Synthetic restore failure' },
          state.restoreStatus
        )
      }
      return fulfill({ ok: true, id: 3, display_id: 'QNR-3' })
    }
    if (/^\/api\/questionnaires\/\d+$/.test(pathName) && method === 'DELETE') {
      if (state.archiveHold) await state.archiveHold
      if (state.archiveStatus !== 200) {
        return fulfill(
          { detail: 'Synthetic archive failure' },
          state.archiveStatus
        )
      }
      return fulfill({ ok: true, id: 3, display_id: 'QNR-3' })
    }
    if (pathName === '/api/questionnaires/bulk-delete' && method === 'POST') {
      return fulfill({ deleted: 1, errors: [] })
    }
    if (pathName === '/api/jobs' && method === 'GET') {
      return fulfill({ items: state.jobs, next_before_id: null })
    }
    if (pathName === '/api/jobs/15' && method === 'GET') {
      state.jobPolls += 1
      if (state.jobPolls === 1) return fulfill({ id: 15, status: 'queued' })
      if (state.jobMode === 'failed')
        return fulfill({ id: 15, status: 'failed' })
      state.qnrs = [
        qnr({
          id: 8,
          display_id: 'QNR-8',
          filename: 'synthetic.xlsx',
          status: 'parsed',
          frameworks: ['SOC 2'],
          parse_metadata: JSON.stringify({ count: 3 }),
        }),
        ...state.qnrs.filter((row) => row.id !== 8),
      ]
      return fulfill({
        id: 15,
        status: 'completed',
        progress: state.completedProgress,
      })
    }
    if (pathName === '/api/jobs/15/retry' && method === 'POST') {
      if (state.retryHold) await state.retryHold
      return fulfill({ id: 15, status: 'queued' })
    }
    if (pathName.endsWith('/unread-count')) return fulfill({ count: 0 })
    if (pathName === '/api/auth/alerts') return fulfill({ alerts: [] })
    if (pathName === '/api/dashboard/cards') {
      return fulfill({ cards: [], has_custom: false })
    }
    if (pathName === '/api/dashboard/cards/allowed-routes') {
      return fulfill({
        routes: ['/dashboard/questionnaires'],
        icons: ['document'],
        sizes: ['medium'],
        visibility_scopes: ['all'],
      })
    }
    if (pathName === '/api/workspaces/creation-policy') {
      return fulfill({ can_create: false })
    }
    return fulfill({})
  })
  return { state, calls }
}

function listReads(calls: Call[]) {
  return calls.filter(
    (call) => call.path === '/api/questionnaires' && call.method === 'GET'
  )
}

async function open(page: Page) {
  await page.goto('/dashboard/questionnaires')
  await expect(
    page.getByRole('heading', { name: 'Questionnaires', exact: true })
  ).toBeVisible()
}

async function noHorizontalOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
}

async function audit(page: Page, surface: string, width: number) {
  const result = await new AxeBuilder({ page }).analyze()
  const violations = result.violations.map((item) => ({
    id: item.id,
    impact: item.impact,
    nodes: item.nodes.length,
  }))
  mkdirSync(evidenceDir, { recursive: true })
  writeFileSync(
    path.join(evidenceDir, `axe-${surface}-${width}.json`),
    JSON.stringify(
      { width, surface, violationCount: violations.length, violations },
      null,
      2
    )
  )
  expect(violations).toEqual([])
}

test('search is debounced, stale responses are dropped, and page or sort are not sent', async ({
  page,
}) => {
  const alpha = gate()
  const { state, calls } = await setup(page, {
    qnrs: [
      qnr({ filename: 'Alpha.xlsx' }),
      qnr({ id: 4, display_id: 'QNR-4', filename: 'Beta.xlsx' }),
    ],
  })
  state.alphaHold = alpha.wait
  await open(page)
  await expect(page.getByText('Alpha.xlsx')).toBeVisible()
  await expect(
    page.getByText(
      'The questionnaire list returns every match in one response, sorted by newest first. It does not accept page, page size, or sort parameters.'
    )
  ).toBeVisible()
  const initial = listReads(calls)
  expect(initial.length).toBeGreaterThan(0)
  for (const call of initial) {
    expect(call.search).not.toMatch(/[?&](?:page|page_size|sort|order)=/)
  }
  const search = page.getByLabel('Search questionnaires')
  await search.pressSequentially('abc', { delay: 40 })
  await page.waitForTimeout(120)
  expect(
    listReads(calls).filter((call) => call.search.includes('search='))
  ).toHaveLength(0)
  await expect
    .poll(() =>
      listReads(calls).filter((call) => call.search.includes('search=abc'))
    )
    .toHaveLength(1)
  await search.fill('alpha')
  await expect
    .poll(() =>
      listReads(calls).filter((call) => call.search.includes('search=alpha'))
    )
    .toHaveLength(1)
  await search.fill('beta')
  await expect
    .poll(() =>
      listReads(calls).filter((call) => call.search.includes('search=beta'))
    )
    .toHaveLength(1)
  await expect(page.getByText('Beta.xlsx')).toBeVisible()
  alpha.release()
  await page.waitForTimeout(400)
  await expect(page.getByText('Alpha.xlsx')).toHaveCount(0)
  await expect(page.getByText('Beta.xlsx')).toBeVisible()
})

test('selection resets when the filter or workspace changes and states its scope', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await expect(
    page.getByText(
      'Selection applies to every questionnaire in this result for the current workspace. Changing the workspace or a filter clears it. This result is not a page.'
    )
  ).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select QNR-3' }).check()
  await expect(
    page.getByText('1 questionnaire selected in this result')
  ).toBeVisible()
  await page.getByLabel('Framework').selectOption('HIPAA')
  await expect(
    page.getByText('1 questionnaire selected in this result')
  ).toHaveCount(0)
  await expect(
    page.getByRole('checkbox', { name: 'Select QNR-3' })
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Remove HIPAA filter' }).click()
  await expect(page.getByText('Vendor.xlsx')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select QNR-3' }).check()
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(page.getByText('Second.xlsx')).toBeVisible()
  await expect(
    page.getByText('1 questionnaire selected in this result')
  ).toHaveCount(0)
  expect(
    listReads(calls).some((call) => call.search.includes('workspace_id=8'))
  ).toBe(true)
})

test('no questionnaires, no matches, and a failed read are different states', async ({
  page,
}) => {
  const { state } = await setup(page, { qnrs: [] })
  await open(page)
  await expect(page.getByText('No questionnaires yet')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Upload your first questionnaire' })
  ).toBeVisible()
  await expect(page.getByText('No matching questionnaires')).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toHaveCount(0)
  await page.getByLabel('Search questionnaires').fill('zzzz')
  await expect(page.getByText('No matching questionnaires')).toBeVisible()
  await expect(page.getByText('No questionnaires yet')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Upload your first questionnaire' })
  ).toHaveCount(0)
  state.listStatus = 500
  await page.getByRole('button', { name: 'Remove zzzz filter' }).click()
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toBeVisible()
  await expect(page.getByText('No questionnaires yet')).toHaveCount(0)
  await expect(page.getByText('No matching questionnaires')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Upload your first questionnaire' })
  ).toHaveCount(0)
})

test('upload keeps the active filters and waits to say the file is stored', async ({
  page,
}) => {
  const upload = gate()
  const { state, calls } = await setup(page)
  state.uploadHold = upload.wait
  state.jobMode = 'parsed'
  state.completedProgress = { generated: 3, total: 10 }
  await open(page)
  await expect(
    page.getByText('Accepted formats: PDF, DOCX, DOC, XLSX, XLS, and TXT.')
  ).toBeVisible()
  await expect(page.getByText('Size limit: 50 MB.')).toBeVisible()
  await expect(
    page.getByText(
      'Workbook contract: an XLSX or XLS answer cell is read from a header named Answer, Response, Reply, Vendor response, Vendor answer, or Answer text. The parser does not use the next column. A sheet with no answer header stores no answer cell. DOCX and PDF imports do not store a workbook answer cell. A new CSV upload is rejected. CSV parsing applies only to a file that is already stored with a .csv name.'
    )
  ).toBeVisible()
  await expect(page.getByText('Parsing progress: Not reported')).toBeVisible()
  await page.getByLabel('Framework').selectOption('SOC 2')
  await expect
    .poll(() =>
      listReads(calls).some((call) =>
        hasParam(call.search, 'framework', 'SOC 2')
      )
    )
    .toBe(true)
  const beforeUpload = listReads(calls).length
  await page.locator('#qnr-upload').setInputFiles({
    name: 'synthetic.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('synthetic'),
  })
  const dialog = page.getByRole('dialog', { name: 'Upload questionnaire' })
  await dialog.getByRole('button', { name: 'Upload', exact: true }).click()
  await expect(page.locator('[data-upload-state="pending"]')).toHaveText(
    'Uploading'
  )
  await expect(
    page.getByRole('status').filter({ hasText: 'Uploaded' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('status').filter({ hasText: 'Queued' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('status').filter({ hasText: 'Parsed' })
  ).toHaveCount(0)
  upload.release()
  await expect(
    page.getByRole('status').filter({ hasText: 'Uploaded' })
  ).toBeVisible()
  await expect(page.getByText('The file is stored.')).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Queued' })
  ).toBeVisible()
  await expect(page.getByText('Parsing progress: Not reported')).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Parsed' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('status').filter({ hasText: 'Parsed' })
  ).toBeVisible()
  await expect(page.getByText('Parsing progress: 3 of 10')).toBeVisible()
  await expect(page.getByText('Questions: 3')).toBeVisible()
  const followUp = listReads(calls).slice(beforeUpload)
  expect(followUp.length).toBeGreaterThan(0)
  expect(
    followUp.every((call) => hasParam(call.search, 'framework', 'SOC 2'))
  ).toBe(true)
})

test('a failed parse job is not shown as parsed', async ({ page }) => {
  const upload = gate()
  const { state } = await setup(page)
  state.uploadHold = upload.wait
  state.jobMode = 'failed'
  await open(page)
  await page.locator('#qnr-upload').setInputFiles({
    name: 'synthetic.xlsx',
    mimeType:
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    buffer: Buffer.from('synthetic'),
  })
  await page
    .getByRole('dialog', { name: 'Upload questionnaire' })
    .getByRole('button', { name: 'Upload', exact: true })
    .click()
  upload.release()
  await expect(
    page.getByRole('status').filter({ hasText: 'Queued' })
  ).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Failed' })
  ).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Parsed' })
  ).toHaveCount(0)
})

test('retry follows a listed parse job, and missing progress stays unreported', async ({
  page,
}) => {
  const retry = gate()
  const { state } = await setup(page, {
    qnrs: [
      qnr({
        status: 'failed',
        parse_metadata: JSON.stringify({
          count: 0,
          error: 'The workbook could not be read.',
        }),
      }),
      qnr({
        id: 4,
        display_id: 'QNR-4',
        filename: 'Counted.xlsx',
        status: 'parsed',
        parse_metadata: JSON.stringify({ count: 12 }),
        review_reviewed: 3,
        review_total: 12,
        mapping_ambiguous: true,
        mapping_confirmation_url: '/dashboard/questionnaires/4',
      }),
      qnr({
        id: 5,
        display_id: 'QNR-5',
        filename: 'Ambiguous.xlsx',
        status: 'parsed',
        mapping_ambiguous: true,
      }),
      qnr({
        id: 6,
        display_id: 'QNR-6',
        filename: 'Clear.xlsx',
        status: 'parsed',
        mapping_ambiguous: false,
      }),
    ],
    jobs: [answerProgressJob, failedParseJob],
  })
  state.retryHold = retry.wait
  await open(page)
  const failed = page.locator('li').filter({ hasText: 'Vendor.xlsx' })
  await expect(failed.getByText('Questions: 0')).toBeVisible()
  await expect(failed.getByText('Review progress: Not reported')).toBeVisible()
  await expect(failed.getByText('Job progress: Not reported')).toBeVisible()
  await expect(failed.getByText('Mapping: Not reported')).toBeVisible()
  await expect(
    failed.getByText('The workbook could not be read.')
  ).toBeVisible()
  await expect(
    page.getByText(
      'There is no questionnaire reparse route. An administrator can retry a failed parse job when that job is on the newest job page.'
    )
  ).toBeVisible()
  const counted = page.locator('li').filter({ hasText: 'Counted.xlsx' })
  await expect(counted.getByText('Questions: 12')).toBeVisible()
  await expect(counted.getByText('Review: 3 of 12')).toBeVisible()
  await expect(counted.getByText('Job progress: 4 of 10')).toBeVisible()
  const confirm = counted.getByRole('link', { name: 'Confirm mapping' })
  await expect(confirm).toHaveAttribute('href', '/dashboard/questionnaires/4')
  const ambiguous = page.locator('li').filter({ hasText: 'Ambiguous.xlsx' })
  await expect(
    ambiguous.getByRole('button', { name: 'Confirm mapping' })
  ).toBeDisabled()
  await expect(
    ambiguous.getByText('Mapping confirmation is not available.')
  ).toBeVisible()
  const clear = page.locator('li').filter({ hasText: 'Clear.xlsx' })
  await expect(clear.getByText('Questions: Not reported')).toBeVisible()
  await expect(clear.getByText('Review progress: Not reported')).toBeVisible()
  await expect(clear.getByText('Job progress: Not reported')).toBeVisible()
  await expect(clear.getByText('Mapping: Not ambiguous')).toBeVisible()
  await expect(
    clear.getByRole('link', { name: 'Confirm mapping' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('link', { name: 'View parse job 15' })
  ).toHaveAttribute('href', '/dashboard/jobs?workspace_id=7')
  const button = page.getByRole('button', { name: 'Retry parsing for QNR-3' })
  await button.click()
  await expect(page.getByText('Parsing queued for QNR-3')).toHaveCount(0)
  retry.release()
  await expect(page.getByText('Parsing queued for QNR-3')).toBeVisible()
  await confirm.click()
  await expect(page).toHaveURL(/\/dashboard\/questionnaires\/4$/)
})

test('editors do not see parse retry', async ({ page }) => {
  await setup(page, {
    role: 'editor',
    qnrs: [
      qnr({
        status: 'failed',
        parse_metadata: JSON.stringify({
          error: 'The workbook could not be read.',
        }),
      }),
    ],
    jobs: [failedParseJob],
  })
  await open(page)
  await expect(page.getByText('Vendor.xlsx')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Retry parsing for QNR-3' })
  ).toHaveCount(0)
  await expect(
    page.getByText(
      'There is no questionnaire reparse route. An administrator can retry a failed parse job when that job is on the newest job page.'
    )
  ).toBeVisible()
})

test('metadata and restore dialogs wait for the response before confirming', async ({
  page,
}) => {
  const metadata = gate()
  const restore = gate()
  const { state } = await setup(page, {
    qnrs: [
      qnr(),
      qnr({
        id: 9,
        display_id: 'QNR-9',
        filename: 'Archived.xlsx',
        deleted_at: '2026-10-02T12:00:00Z',
        status: 'uploaded',
      }),
    ],
  })
  state.metadataHold = metadata.wait
  state.restoreHold = restore.wait
  await open(page)
  await page.getByRole('button', { name: 'Actions for QNR-3' }).click()
  await page.getByRole('menuitem', { name: 'Edit metadata' }).click()
  const metadataDialog = page.getByRole('dialog', { name: /Edit metadata/ })
  await metadataDialog
    .getByRole('button', { name: 'HIPAA', exact: true })
    .click()
  await metadataDialog
    .getByRole('button', { name: 'Save metadata', exact: true })
    .click()
  const row = page.locator('li').filter({ hasText: 'Vendor.xlsx' })
  await expect(row).not.toContainText('HIPAA')
  await expect(metadataDialog.getByText('Metadata saved.')).toHaveCount(0)
  metadata.release()
  await expect(metadataDialog.getByText('Metadata saved.')).toBeVisible()
  await expect(row).toContainText('HIPAA')
  await metadataDialog
    .getByRole('button', { name: 'Close', exact: true })
    .click()
  await expect(metadataDialog).toHaveCount(0)

  state.metadataStatus = 500
  state.metadataHold = null
  await page.getByRole('button', { name: 'Actions for QNR-3' }).click()
  await page.getByRole('menuitem', { name: 'Edit metadata' }).click()
  const again = page.getByRole('dialog', { name: /Edit metadata/ })
  await again.getByRole('button', { name: 'NIST', exact: true }).click()
  await again
    .getByRole('button', { name: 'Save metadata', exact: true })
    .click()
  await expect(again.getByRole('alert')).toBeVisible()
  await expect(again.getByText('Metadata saved.')).toHaveCount(0)
  await expect(row).not.toContainText('NIST')
  await again.getByRole('button', { name: 'Close', exact: true }).click()

  await page.getByLabel('Archive filter').selectOption('only')
  await expect(page.getByText('Archived.xlsx')).toBeVisible()
  await page.getByRole('button', { name: 'Actions for QNR-9' }).click()
  await page.getByRole('menuitem', { name: 'Restore', exact: true }).click()
  const restoreDialog = page.getByRole('alertdialog', {
    name: 'Restore questionnaire?',
  })
  await restoreDialog
    .getByRole('button', { name: 'Restore', exact: true })
    .click()
  await expect(restoreDialog.getByText('Restored.')).toHaveCount(0)
  restore.release()
  await expect(restoreDialog.getByText('Restored.')).toBeVisible()
  await expect(restoreDialog).toBeVisible()
})

test('archive and delete are different destructive actions', async ({
  page,
}) => {
  const archive = gate()
  const { state, calls } = await setup(page)
  state.archiveHold = archive.wait
  await open(page)
  await page.getByRole('button', { name: 'Actions for QNR-3' }).click()
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  const remove = page.getByRole('alertdialog', { name: 'Delete record?' })
  await expect(remove.getByText('ID: QNR-3')).toBeVisible()
  await expect(
    remove.getByText(
      'Permanent deletion is not available. The questionnaire API archives a questionnaire and does not erase one questionnaire.'
    )
  ).toBeVisible()
  await expect(
    remove.getByRole('button', { name: 'Delete permanently' })
  ).toBeDisabled()
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(0)
  expect(
    calls.filter((call) => call.path.includes('delete-preview'))
  ).toHaveLength(0)
  await remove.getByRole('button', { name: 'Close', exact: true }).click()

  await page.getByRole('button', { name: 'Actions for QNR-3' }).click()
  await page.getByRole('menuitem', { name: 'Archive', exact: true }).click()
  const archiveDialog = page.getByRole('alertdialog', {
    name: 'Archive questionnaire?',
  })
  await expect(archiveDialog.getByText('2 answers')).toBeVisible()
  await archiveDialog
    .getByRole('button', { name: 'Archive', exact: true })
    .click()
  await expect(archiveDialog.getByText('Archived.')).toHaveCount(0)
  await expect
    .poll(() => calls.filter((call) => call.method === 'DELETE').length)
    .toBe(1)
  archive.release()
  await expect(archiveDialog.getByText('Archived.')).toBeVisible()
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)

  await archiveDialog
    .getByRole('button', { name: 'Close', exact: true })
    .click()
  await page.getByRole('checkbox', { name: 'Select QNR-3' }).check()
  await page
    .getByRole('button', { name: 'Archive selected', exact: true })
    .click()
  await expect(
    page.getByRole('alertdialog', { name: 'Archive selected questionnaires?' })
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: /Delete selected/i })
  ).toHaveCount(0)
})

test('reviewers do not see upload, row actions, or delete', async ({
  page,
}) => {
  await setup(page, { role: 'reviewer' })
  await open(page)
  await expect(page.getByText('Vendor.xlsx')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Upload', exact: true })
  ).toHaveCount(0)
  await expect(page.locator('#qnr-upload')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Actions for/ })).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: /Archive|Delete/ })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Upload your first questionnaire' })
  ).toHaveCount(0)
})

test('date and filter fields are labelled and selected filters are chips', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await open(page)
  await expect(page.getByLabel('Search questionnaires')).toBeVisible()
  await expect(page.getByLabel('Framework')).toBeVisible()
  await expect(page.getByLabel('Subject area')).toBeVisible()
  await expect(page.getByLabel('Created from')).toBeVisible()
  await expect(page.getByLabel('Created to')).toBeVisible()
  await expect(page.getByLabel('Questionnaire status')).toBeVisible()
  await expect(page.getByLabel('Archive filter')).toBeVisible()
  await page.getByLabel('Created from').fill('2026-10-01T00:00')
  await page.getByLabel('Questionnaire status').selectOption('failed')
  await expect(
    page.getByRole('button', { name: 'Remove Created from filter' })
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove failed filter' })
  ).toBeVisible()
  await expect
    .poll(() =>
      listReads(calls).some(
        (call) =>
          call.search.includes('created_from=') &&
          call.search.includes('status=failed')
      )
    )
    .toBe(true)
  await page.getByRole('button', { name: 'Remove failed filter' }).click()
  await expect(page.getByLabel('Questionnaire status')).toHaveValue('')
})

for (const width of [360, 768, 1440]) {
  test(`questionnaires stay usable at ${width}px`, async ({
    page,
  }, testInfo) => {
    const longName = `${'A'.repeat(80)} questionnaire.xlsx`
    const { state } = await setup(page, {
      qnrs: [
        qnr({
          filename: longName,
          status: 'failed',
          parse_metadata: JSON.stringify({
            error:
              'The parser stopped before any question was stored. This sentence is intentionally long so the row has to wrap inside a narrow viewport without clipping the actions.',
          }),
        }),
      ],
    })
    await page.setViewportSize({ width, height: 900 })
    await open(page)
    await expect(page.getByText(longName)).toBeVisible()
    await noHorizontalOverflow(page)
    const search = page.getByLabel('Search questionnaires')
    await search.focus()
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Framework')).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(search).toBeFocused()
    const actions = page.getByRole('button', { name: 'Actions for QNR-3' })
    await actions.focus()
    await page.keyboard.press('Enter')
    await page.getByRole('menuitem', { name: 'Archive', exact: true }).click()
    const dialog = page.getByRole('alertdialog', {
      name: 'Archive questionnaire?',
    })
    await expect(dialog).toBeVisible()
    for (let index = 0; index < 4; index += 1) {
      await page.keyboard.press('Tab')
      expect(
        await dialog.evaluate((node) => node.contains(document.activeElement))
      ).toBe(true)
    }
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    mkdirSync(path.join(evidenceDir, 'screenshots'), { recursive: true })
    await audit(page, 'ready', width)
    const readyShot = path.join(
      evidenceDir,
      'screenshots',
      `ready-${width}.png`
    )
    await page.screenshot({ path: readyShot, fullPage: true })
    await testInfo.attach(`ready-${width}`, {
      path: readyShot,
      contentType: 'image/png',
    })

    state.qnrs = []
    state.listStatus = 200
    await page.reload()
    await expect(page.getByText('No questionnaires yet')).toBeVisible()
    await noHorizontalOverflow(page)
    await audit(page, 'empty', width)
    const emptyShot = path.join(
      evidenceDir,
      'screenshots',
      `empty-${width}.png`
    )
    await page.screenshot({ path: emptyShot, fullPage: true })
    await testInfo.attach(`empty-${width}`, {
      path: emptyShot,
      contentType: 'image/png',
    })

    state.listStatus = 500
    await page.reload()
    const error = page.getByRole('heading', { name: 'Something went wrong' })
    await expect(error).toBeVisible()
    await page.getByRole('button', { name: 'Try again' }).focus()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeFocused()
    await noHorizontalOverflow(page)
    await audit(page, 'error', width)
    const errorShot = path.join(
      evidenceDir,
      'screenshots',
      `error-${width}.png`
    )
    await page.screenshot({ path: errorShot, fullPage: true })
    await testInfo.attach(`error-${width}`, {
      path: errorShot,
      contentType: 'image/png',
    })
  })
}
