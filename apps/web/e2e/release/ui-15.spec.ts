import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Deterministic control paths for /dashboard/documents. Real API qualification
// stays outside this spec. The list endpoint has no page or sort parameters.
test.use({ storageState: { cookies: [], origins: [] } })
test.describe.configure({ timeout: 90_000 })

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-15-016'
)

type Doc = {
  id: number
  display_id: string
  filename: string
  file_type: string
  status: string
  index_error: string | null
  created_at: string
  deleted_at: string | null
  frameworks: string[]
  subject_areas: string[]
  source_eligibility?: string
  freshness?: string
  version?: string
  source_preview_url?: string
}

type RoleName = 'admin' | 'editor' | 'reviewer'

function doc(overrides: Partial<Doc> = {}): Doc {
  return {
    id: 3,
    display_id: 'DOC-3',
    filename: 'Policy.pdf',
    file_type: 'pdf',
    status: 'uploaded',
    index_error: null,
    created_at: '2026-10-01T12:00:00Z',
    deleted_at: null,
    frameworks: ['SOC 2'],
    subject_areas: ['Access Control'],
    ...overrides,
  }
}

const failedIndexJob = {
  id: 15,
  kind: 'index_document',
  status: 'failed',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:00:00',
  started_at: null,
  completed_at: '2026-10-30T12:05:00',
  next_attempt_at: null,
  retry_scheduled: false,
  retries_exhausted: true,
  charge_uncertain: false,
  progress: null,
  outcome: null,
  object_ref: { type: 'document', id: 3 },
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

async function setup(
  page: Page,
  options: {
    role?: RoleName
    docs?: Doc[]
    otherDocs?: Doc[]
    jobs?: unknown[]
    listStatus?: number
  } = {}
) {
  const role = options.role ?? 'admin'
  const state = {
    workspace: 7,
    docs: options.docs ?? [doc()],
    otherDocs: options.otherDocs ?? [
      doc({
        id: 8,
        display_id: 'DOC-8',
        filename: 'Second.pdf',
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
    bulkHold: null as Promise<void> | null,
    retryHold: null as Promise<void> | null,
    uploadStatus: 200,
    metadataStatus: 200,
    restoreStatus: 200,
    archiveStatus: 200,
    jobMode: 'indexed' as 'indexed' | 'failed',
    jobPolls: 0,
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
    if (pathName === '/api/documents' && method === 'GET') {
      const search = url.searchParams.get('search') || ''
      if (search === 'alpha' && state.alphaHold) await state.alphaHold
      if (state.listStatus !== 200) {
        return fulfill({ detail: 'Synthetic read failure' }, state.listStatus)
      }
      let rows = state.workspace === 7 ? [...state.docs] : [...state.otherDocs]
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
    if (pathName === '/api/documents/upload' && method === 'POST') {
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
        display_id: 'DOC-8',
        filename: 'synthetic.pdf',
        status: 'uploaded',
        job_id: 15,
      })
    }
    if (/^\/api\/documents\/\d+\/delete-preview$/.test(pathName)) {
      return fulfill({
        dependencies: { questionnaires: 2, generated_answers: 0 },
        recommended_action: 'archive',
        unmodeled_warning: null,
      })
    }
    if (
      /^\/api\/documents\/\d+\/metadata$/.test(pathName) &&
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
      /^\/api\/documents\/\d+\/restore$/.test(pathName) &&
      method === 'POST'
    ) {
      if (state.restoreHold) await state.restoreHold
      if (state.restoreStatus !== 200) {
        return fulfill(
          { detail: 'Synthetic restore failure' },
          state.restoreStatus
        )
      }
      return fulfill({ ok: true, id: 3, display_id: 'DOC-3' })
    }
    if (/^\/api\/documents\/\d+$/.test(pathName) && method === 'DELETE') {
      if (state.archiveHold) await state.archiveHold
      if (state.archiveStatus !== 200) {
        return fulfill(
          { detail: 'Synthetic archive failure' },
          state.archiveStatus
        )
      }
      return fulfill({ ok: true, id: 3, display_id: 'DOC-3' })
    }
    if (pathName === '/api/documents/bulk-delete' && method === 'POST') {
      if (state.bulkHold) await state.bulkHold
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
      state.docs = [
        doc({
          id: 8,
          display_id: 'DOC-8',
          filename: 'synthetic.pdf',
          status: 'indexed',
        }),
        ...state.docs.filter((row) => row.id !== 8),
      ]
      return fulfill({ id: 15, status: 'completed' })
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
        routes: ['/dashboard/documents'],
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

function documentReads(calls: Call[]) {
  return calls.filter(
    (call) => call.path === '/api/documents' && call.method === 'GET'
  )
}

async function open(page: Page) {
  await page.goto('/dashboard/documents')
  await expect(
    page.getByRole('heading', { name: 'Documents', exact: true })
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
    docs: [
      doc({ filename: 'Alpha.pdf' }),
      doc({ id: 4, display_id: 'DOC-4', filename: 'Beta.pdf' }),
    ],
  })
  state.alphaHold = alpha.wait
  await open(page)
  await expect(page.getByText('Alpha.pdf')).toBeVisible()
  await expect(
    page.getByText(
      'The document list returns every match in one response, sorted by newest first. It does not accept page, page size, or sort parameters.'
    )
  ).toBeVisible()
  const initial = documentReads(calls)
  expect(initial.length).toBeGreaterThan(0)
  for (const call of initial) {
    expect(call.search).not.toMatch(/[?&](?:page|page_size|sort|order)=/)
  }
  const search = page.getByLabel('Search documents')
  await search.pressSequentially('abc', { delay: 40 })
  await page.waitForTimeout(120)
  expect(
    documentReads(calls).filter((call) => call.search.includes('search='))
  ).toHaveLength(0)
  await expect
    .poll(() =>
      documentReads(calls).filter((call) => call.search.includes('search=abc'))
    )
    .toHaveLength(1)
  await search.fill('alpha')
  await expect
    .poll(() =>
      documentReads(calls).filter((call) =>
        call.search.includes('search=alpha')
      )
    )
    .toHaveLength(1)
  await search.fill('beta')
  await expect
    .poll(() =>
      documentReads(calls).filter((call) => call.search.includes('search=beta'))
    )
    .toHaveLength(1)
  await expect(page.getByText('Beta.pdf')).toBeVisible()
  alpha.release()
  await page.waitForTimeout(400)
  await expect(page.getByText('Alpha.pdf')).toHaveCount(0)
  await expect(page.getByText('Beta.pdf')).toBeVisible()
})

test('selection resets when the filter or workspace changes and states its scope', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await expect(
    page.getByText(
      'Selection applies to every document in this result for the current workspace. Changing the workspace or a filter clears it. This result is not a page.'
    )
  ).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select DOC-3' }).check()
  await expect(
    page.getByText('1 document selected in this result')
  ).toBeVisible()
  await page.getByLabel('Framework').selectOption('HIPAA')
  await expect(
    page.getByText('1 document selected in this result')
  ).toHaveCount(0)
  await expect(
    page.getByRole('checkbox', { name: 'Select DOC-3' })
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Remove HIPAA filter' }).click()
  await expect(page.getByText('Policy.pdf')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Select DOC-3' }).check()
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(page.getByText('Second.pdf')).toBeVisible()
  await expect(
    page.getByText('1 document selected in this result')
  ).toHaveCount(0)
  expect(
    documentReads(calls).some((call) => call.search.includes('workspace_id=8'))
  ).toBe(true)
})

test('no documents, no matches, and a failed read are different states', async ({
  page,
}) => {
  const { state } = await setup(page, { docs: [] })
  await open(page)
  await expect(page.getByText('No documents yet')).toBeVisible()
  await expect(page.getByText('No matching documents')).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toHaveCount(0)
  await page.getByLabel('Search documents').fill('zzzz')
  await expect(page.getByText('No matching documents')).toBeVisible()
  await expect(page.getByText('No documents yet')).toHaveCount(0)
  state.listStatus = 500
  await page.getByRole('button', { name: 'Remove zzzz filter' }).click()
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toBeVisible()
  await expect(page.getByText('No documents yet')).toHaveCount(0)
  await expect(page.getByText('No matching documents')).toHaveCount(0)
})

test('accepted formats and the size limit show before a file is chosen', async ({
  page,
}) => {
  const upload = gate()
  const { state } = await setup(page)
  state.uploadHold = upload.wait
  state.jobMode = 'indexed'
  await open(page)
  await expect(
    page.getByText('Accepted formats: PDF, DOCX, DOC, XLSX, XLS, and TXT.')
  ).toBeVisible()
  await expect(page.getByText('Size limit: 50 MB.')).toBeVisible()
  await expect(page.getByText('Allowed:')).toHaveCount(0)
  await page.locator('#doc-upload').setInputFiles({
    name: 'synthetic.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('synthetic'),
  })
  const dialog = page.getByRole('dialog', { name: 'Upload Evidence Document' })
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
    page.getByRole('status').filter({ hasText: 'Indexed' })
  ).toHaveCount(0)
  upload.release()
  await expect(
    page.getByRole('status').filter({ hasText: 'Uploaded' })
  ).toBeVisible()
  await expect(page.getByText('The file is stored.')).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Queued' })
  ).toBeVisible()
  await expect(
    page.getByRole('status').filter({ hasText: 'Indexed' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('status').filter({ hasText: 'Indexed' })
  ).toBeVisible()
})

test('a failed index job is not shown as indexed', async ({ page }) => {
  const upload = gate()
  const { state } = await setup(page)
  state.uploadHold = upload.wait
  state.jobMode = 'failed'
  await open(page)
  await page.locator('#doc-upload').setInputFiles({
    name: 'synthetic.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('synthetic'),
  })
  await page
    .getByRole('dialog', { name: 'Upload Evidence Document' })
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
    page.getByRole('status').filter({ hasText: 'Indexed' })
  ).toHaveCount(0)
})

test('retry follows a listed index job, and missing source fields stay unreported', async ({
  page,
}) => {
  const retry = gate()
  const { state } = await setup(page, {
    docs: [
      doc({
        status: 'failed',
        index_error: 'Could not read the file.',
        source_eligibility: 'eligible',
        freshness: 'fresh',
        version: 'v3',
        source_preview_url: '/dashboard/jobs?workspace_id=7',
      }),
      doc({
        id: 4,
        display_id: 'DOC-4',
        filename: 'Notes.txt',
        file_type: 'txt',
        status: 'indexed',
      }),
    ],
    jobs: [failedIndexJob],
  })
  state.retryHold = retry.wait
  await open(page)
  await expect(page.getByText('Source eligibility: eligible')).toBeVisible()
  await expect(page.getByText('Freshness: fresh')).toBeVisible()
  await expect(page.getByText('Version: v3')).toBeVisible()
  await expect(page.getByText('Source eligibility: Not reported')).toBeVisible()
  await expect(page.getByText('Freshness: Not reported')).toBeVisible()
  await expect(page.getByText('Version: Not reported')).toBeVisible()
  await expect(page.getByText('Reindex is not offered.')).toBeVisible()
  const source = page.getByRole('link', { name: 'View source' })
  await expect(source).toHaveAttribute('href', '/dashboard/jobs?workspace_id=7')
  await expect(
    page.getByRole('link', { name: 'View index job 15' })
  ).toHaveAttribute('href', '/dashboard/jobs?workspace_id=7')
  const button = page.getByRole('button', { name: 'Retry indexing for DOC-3' })
  await button.click()
  await expect(page.getByText('Indexing queued for DOC-3')).toHaveCount(0)
  retry.release()
  await expect(page.getByText('Indexing queued for DOC-3')).toBeVisible()
  await source.click()
  await expect(
    page.getByRole('heading', { name: 'Jobs', exact: true })
  ).toBeVisible()
})

test('editors do not see index retry', async ({ page }) => {
  await setup(page, {
    role: 'editor',
    docs: [doc({ status: 'failed', index_error: 'Could not read the file.' })],
    jobs: [failedIndexJob],
  })
  await open(page)
  await expect(page.getByText('Policy.pdf')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Retry indexing for DOC-3' })
  ).toHaveCount(0)
  await expect(page.getByText('Reindex is not offered.')).toBeVisible()
})

test('metadata and restore dialogs wait for the response before confirming', async ({
  page,
}) => {
  const metadata = gate()
  const restore = gate()
  const { state } = await setup(page, {
    docs: [
      doc(),
      doc({
        id: 9,
        display_id: 'DOC-9',
        filename: 'Archived.pdf',
        deleted_at: '2026-10-02T12:00:00Z',
        status: 'uploaded',
      }),
    ],
  })
  state.metadataHold = metadata.wait
  state.restoreHold = restore.wait
  await open(page)
  await page.getByRole('button', { name: 'Actions for DOC-3' }).click()
  await page.getByRole('menuitem', { name: 'Edit metadata' }).click()
  const metadataDialog = page.getByRole('dialog', { name: /Edit metadata/ })
  await metadataDialog
    .getByRole('button', { name: 'HIPAA', exact: true })
    .click()
  await metadataDialog
    .getByRole('button', { name: 'Save metadata', exact: true })
    .click()
  const row = page.locator('li').filter({ hasText: 'Policy.pdf' })
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
  await page.getByRole('button', { name: 'Actions for DOC-3' }).click()
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
  await expect(page.getByText('Archived.pdf')).toBeVisible()
  await page.getByRole('button', { name: 'Actions for DOC-9' }).click()
  await page.getByRole('menuitem', { name: 'Restore', exact: true }).click()
  const restoreDialog = page.getByRole('alertdialog', {
    name: 'Restore document?',
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
  await page.getByRole('button', { name: 'Actions for DOC-3' }).click()
  await page.getByRole('menuitem', { name: 'Delete', exact: true }).click()
  const remove = page.getByRole('alertdialog', { name: 'Delete record?' })
  await expect(remove.getByText('ID: DOC-3')).toBeVisible()
  await expect(
    remove.getByText(
      'Permanent deletion is not available. The document API archives a document and does not erase one document.'
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

  await page.getByRole('button', { name: 'Actions for DOC-3' }).click()
  await page.getByRole('menuitem', { name: 'Archive', exact: true }).click()
  const archiveDialog = page.getByRole('alertdialog', {
    name: 'Archive document?',
  })
  await expect(archiveDialog.getByText('2 questionnaires')).toBeVisible()
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
  await page.getByRole('checkbox', { name: 'Select DOC-3' }).check()
  await page
    .getByRole('button', { name: 'Archive selected', exact: true })
    .click()
  await expect(
    page.getByRole('alertdialog', { name: 'Archive selected documents?' })
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
  await expect(page.getByText('Policy.pdf')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Upload', exact: true })
  ).toHaveCount(0)
  await expect(page.locator('#doc-upload')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Actions for/ })).toHaveCount(0)
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: /Archive|Delete/ })
  ).toHaveCount(0)
})

test('date and filter fields are labelled and selected filters are chips', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await open(page)
  await expect(page.getByLabel('Search documents')).toBeVisible()
  await expect(page.getByLabel('Framework')).toBeVisible()
  await expect(page.getByLabel('Subject area')).toBeVisible()
  await expect(page.getByLabel('Created from')).toBeVisible()
  await expect(page.getByLabel('Created to')).toBeVisible()
  await expect(page.getByLabel('Document status')).toBeVisible()
  await expect(page.getByLabel('Archive filter')).toBeVisible()
  await page.getByLabel('Created from').fill('2026-10-01T00:00')
  await page.getByLabel('Document status').selectOption('failed')
  await expect(
    page.getByRole('button', { name: 'Remove Created from filter' })
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Remove failed filter' })
  ).toBeVisible()
  await expect
    .poll(() =>
      documentReads(calls).some(
        (call) =>
          call.search.includes('created_from=') &&
          call.search.includes('status=failed')
      )
    )
    .toBe(true)
  await page.getByRole('button', { name: 'Remove failed filter' }).click()
  await expect(page.getByLabel('Document status')).toHaveValue('')
})

for (const width of [360, 768, 1440]) {
  test(`documents stay usable at ${width}px`, async ({ page }, testInfo) => {
    const longName = `${'A'.repeat(80)} evidence file.pdf`
    const { state } = await setup(page, {
      docs: [
        doc({
          filename: longName,
          status: 'failed',
          index_error:
            'The extractor stopped before any text was stored. This sentence is intentionally long so the row has to wrap inside a narrow viewport without clipping the actions.',
        }),
      ],
    })
    await page.setViewportSize({ width, height: 900 })
    await open(page)
    await expect(page.getByText(longName)).toBeVisible()
    await noHorizontalOverflow(page)
    const search = page.getByLabel('Search documents')
    await search.focus()
    await page.keyboard.press('Tab')
    await expect(page.getByLabel('Framework')).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(search).toBeFocused()
    const actions = page.getByRole('button', { name: 'Actions for DOC-3' })
    await actions.focus()
    await page.keyboard.press('Enter')
    await page.getByRole('menuitem', { name: 'Archive', exact: true }).click()
    const dialog = page.getByRole('alertdialog', { name: 'Archive document?' })
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

    state.docs = []
    state.listStatus = 200
    await page.reload()
    await expect(page.getByText('No documents yet')).toBeVisible()
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
