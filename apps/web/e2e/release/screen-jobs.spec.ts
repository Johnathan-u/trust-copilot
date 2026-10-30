import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Deterministic browser control paths. Real API/DB qualification remains separate.
test.use({ storageState: { cookies: [], origins: [] } })
const job = {
  id: 41,
  kind: 'generate_answers',
  status: 'running',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:00:00',
  started_at: '2026-10-30T12:01:00',
  completed_at: null,
  next_attempt_at: null,
  retry_scheduled: false,
  retries_exhausted: false,
  charge_uncertain: true,
  progress: { generated: 2, total: 5 },
  outcome: null,
  object_ref: { type: 'questionnaire', id: 9 },
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
async function setup(page: Page, role = 'admin') {
  const state = {
    workspace: 7,
    rows: [job] as Array<Record<string, unknown>>,
    next: null as number | null,
    readStatus: 200,
    readWait: Promise.resolve(),
    malformed: false,
    detail: async (route: Route) =>
      json(route, {
        ...job,
        result: { generated: 3, total: 5, storage_key: 'PRIVATE_DETAIL' },
        error: 'PRIVATE_DETAIL',
      }),
    mutation: async (route: Route) => {
      const retry = new URL(route.request().url()).pathname.endsWith('/retry')
      const updated = {
        ...job,
        status: retry ? 'queued' : 'cancelled',
        attempt: retry ? 0 : 1,
      }
      state.rows = [updated]
      return json(route, updated)
    },
  }
  const calls: Array<{ pathname: string; method: string; search: string }> = []
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
    const p = url.pathname
    calls.push({ pathname: p, method: request.method(), search: url.search })
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
        can_review: role !== 'custom-denied',
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
    if (p === '/api/auth/me') return json(route, me)
    if (p === '/api/auth/switch-workspace') {
      state.workspace = request.postDataJSON().workspace_id
      return json(route, {
        ...me,
        workspace_id: state.workspace,
        workspace_name: 'Second workspace',
      })
    }
    if (p === '/api/jobs') {
      const rows =
        state.workspace === 7
          ? state.rows
          : [
              {
                ...job,
                id: 81,
                kind: 'export',
                status: 'completed',
                charge_uncertain: false,
              },
            ]
      const payload = state.malformed
        ? { unexpected: [] }
        : { items: rows, next_before_id: state.next }
      const status = state.readStatus
      const waiting = state.workspace === 7 ? state.readWait : Promise.resolve()
      await waiting
      // A workspace switch may abort this deliberately delayed response.
      return json(
        route,
        status === 200 ? payload : { detail: 'PRIVATE_READ' },
        status
      ).catch(() => {})
    }
    if (/^\/api\/jobs\/\d+$/.test(p)) return state.detail(route)
    if (/^\/api\/jobs\/\d+\/(cancel|retry)$/.test(p))
      return state.mutation(route)
    if (p.endsWith('/unread-count')) return json(route, { count: 0 })
    if (p === '/api/auth/alerts') return json(route, { alerts: [] })
    if (p === '/api/dashboard/cards')
      return json(route, { cards: [], has_custom: false })
    if (p === '/api/dashboard/cards/allowed-routes')
      return json(route, {
        routes: ['/dashboard/jobs'],
        icons: ['document'],
        sizes: ['medium'],
        visibility_scopes: ['all'],
      })
    if (p === '/api/workspaces/creation-policy')
      return json(route, { can_create: false })
    return json(route, {})
  })
  return { state, calls }
}
async function open(page: Page, query = '') {
  await page.goto(`/dashboard/jobs${query}`)
  await expect(
    page.getByRole('heading', { name: 'Jobs', exact: true })
  ).toBeVisible()
}
async function confirm(page: Page, action: 'Cancel job' | 'Retry job') {
  await page.getByRole('button', { name: action, exact: true }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: action, exact: true }).click()
}
const history = (page: Page) =>
  page.getByRole('region', { name: 'Job history' })

test('cursor survives reload, respects Back, and does one initial business read', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  state.next = 41
  await open(page)
  await expect(page.getByText('2 of 5 answers generated')).toBeVisible()
  expect(calls.filter((c) => c.pathname === '/api/jobs')).toHaveLength(1)
  state.rows = [{ ...job, id: 40, kind: 'export' }]
  state.next = null
  await page.getByRole('button', { name: 'Older jobs' }).click()
  await expect(page).toHaveURL(/workspace_id=7&before_id=41$/)
  await expect(
    page.getByRole('article', { name: 'Export questionnaire' })
  ).toBeVisible()
  await page.reload()
  await expect(
    page.getByRole('article', { name: 'Export questionnaire' })
  ).toBeVisible()
  expect(
    calls
      .filter((c) => c.pathname === '/api/jobs')
      .slice(-2)
      .every((c) => new URLSearchParams(c.search).get('before_id') === '41')
  ).toBe(true)
  state.rows = [job]
  state.next = 41
  await page.goBack()
  await expect(page).toHaveURL(/\/dashboard\/jobs$/)
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toBeVisible()
})
test('current job types expose only checked object links and measured progress', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = [
    'generate_answers',
    'export',
    'parse_questionnaire',
    'parse_evidence',
    'index_document',
  ].map((kind, i) => ({
    ...job,
    id: 45 - i,
    kind,
    object_ref:
      i < 3 ? { type: 'questionnaire', id: 9 } : { type: 'document', id: 8 },
  }))
  await open(page)
  await expect(page.getByRole('article')).toHaveCount(5)
  await expect(
    page.getByRole('progressbar', { name: 'Answers generated' })
  ).toHaveAttribute('value', '2')
  await expect(
    page.getByRole('link', { name: 'Open questionnaire' })
  ).toHaveCount(3)
  await expect(
    page.getByRole('link', { name: 'Open document library' })
  ).toHaveCount(2)
  for (const link of await page
    .getByRole('link', { name: 'Open questionnaire' })
    .all())
    await expect(link).toHaveAttribute('href', '/dashboard/questionnaires/9')
  for (const link of await page
    .getByRole('link', { name: 'Open document library' })
    .all())
    await expect(link).toHaveAttribute('href', '/dashboard/documents')
})
test('unknown jobs and missing object references never expose internal fields or actions', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = [
    {
      ...job,
      kind: 'PRIVATE_RAW',
      status: 'PRIVATE_RAW',
      object_ref: null,
      payload: 'PRIVATE_RAW',
      error: 'PRIVATE_RAW',
    },
  ]
  await open(page)
  await expect(page.getByText('Unrecognized job')).toBeVisible()
  await expect(page.getByText('Status unavailable')).toBeVisible()
  await expect(history(page).getByRole('link')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: /^(Cancel|Retry) job$/ })
  ).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('PRIVATE_RAW')
})
test('empty persisted history is explicit', async ({ page }) => {
  const { state } = await setup(page)
  state.rows = []
  await open(page)
  await expect(page.getByRole('heading', { name: 'No jobs yet' })).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
})
test('loading remains separate from empty history', async ({ page }) => {
  const { state } = await setup(page)
  const pending = gate()
  state.readWait = pending.wait
  await open(page)
  await expect(history(page).locator('[data-state="loading"]')).toBeVisible()
  await expect(page.getByText('No jobs yet')).toHaveCount(0)
  pending.release()
  await expect(page.getByText('2 of 5 answers generated')).toBeVisible()
})
test('failed history can be retried without exposing server detail', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.readStatus = 500
  await open(page)
  await expect(history(page).getByRole('alert')).toContainText(
    'Something went wrong'
  )
  await expect(page.locator('body')).not.toContainText('PRIVATE_READ')
  state.readStatus = 200
  await history(page).getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('2 of 5 answers generated')).toBeVisible()
})
test('malformed successful history is not a false empty state', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.malformed = true
  await open(page)
  await expect(history(page).getByRole('alert')).toContainText(
    'The response could not be read'
  )
  await expect(page.getByText('No jobs yet')).toHaveCount(0)
})
for (const status of [401, 403, 404])
  test(`history access loss ${status} clears previous rows and links`, async ({
    page,
  }) => {
    const { state } = await setup(page)
    await open(page)
    await expect(
      page.getByRole('article', { name: 'Generate answers' })
    ).toBeVisible()
    state.readStatus = status
    await page.getByRole('button', { name: 'Reload jobs' }).click()
    await expect(history(page).getByRole('alert')).toBeVisible()
    await expect(page.getByRole('article')).toHaveCount(0)
    await expect(
      page.getByRole('link', { name: 'Open questionnaire' })
    ).toHaveCount(0)
  })
test('legacy detail only displays safe counters and lifecycle fields', async ({
  page,
}) => {
  await setup(page)
  await open(page)
  await page.getByRole('button', { name: 'View details' }).click()
  const dialog = page.getByRole('dialog', { name: 'Job details' })
  await expect(dialog.getByText('3 of 5 answers generated')).toBeVisible()
  await expect(dialog).not.toContainText('PRIVATE_DETAIL')
  await expect(dialog.getByRole('link')).toHaveCount(0)
})
test('not-found detail preserves the independently loaded history', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.detail = (route) => json(route, { detail: 'PRIVATE_DETAIL' }, 404)
  await open(page)
  await page.getByRole('button', { name: 'View details' }).click()
  const dialog = page.getByRole('dialog', { name: 'Job details' })
  await expect(dialog.getByRole('alert')).toContainText(
    'We could not find that'
  )
  await dialog.getByRole('button', { name: 'Close', exact: true }).click()
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toBeVisible()
})
for (const status of [401, 403])
  test(`detail denial ${status} clears private history and aborts a pending list`, async ({
    page,
  }) => {
    const { state, calls } = await setup(page)
    await open(page)
    await expect(
      page.getByRole('article', { name: 'Generate answers' })
    ).toBeVisible()
    const pending = gate()
    state.readWait = pending.wait
    state.detail = (route) => json(route, { detail: 'PRIVATE_DENIAL' }, status)
    await page.getByRole('button', { name: 'Reload jobs' }).click()
    await expect
      .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
      .toBe(2)
    const aborted = page.waitForEvent(
      'requestfailed',
      (request) => new URL(request.url()).pathname === '/api/jobs'
    )
    await page.getByRole('button', { name: 'View details' }).click()
    await aborted
    pending.release()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(history(page).getByRole('alert')).toBeVisible()
    await expect(page.getByRole('article')).toHaveCount(0)
    await expect(
      page.getByRole('link', { name: 'Open questionnaire' })
    ).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cancel job' })).toHaveCount(
      0
    )
    await expect(page.locator('body')).not.toContainText('PRIVATE_DENIAL')
  })
for (const status of [401, 403, 404])
  test(`history denial ${status} closes detail and rejects its late response`, async ({
    page,
  }) => {
    const { state, calls } = await setup(page)
    await open(page)
    await expect(
      page.getByRole('article', { name: 'Generate answers' })
    ).toBeVisible()
    const list = gate()
    const detail = gate()
    state.readWait = list.wait
    state.readStatus = status
    state.detail = async (route) => {
      await detail.wait
      return json(route, { ...job, result: { generated: 5, total: 5 } }).catch(
        () => {}
      )
    }
    await page.getByRole('button', { name: 'Reload jobs' }).click()
    await expect
      .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
      .toBe(2)
    await page.getByRole('button', { name: 'View details' }).click()
    await expect
      .poll(() => calls.filter((c) => c.pathname === '/api/jobs/41').length)
      .toBe(1)
    const aborted = page.waitForEvent(
      'requestfailed',
      (request) => new URL(request.url()).pathname === '/api/jobs/41'
    )
    list.release()
    await aborted
    detail.release()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(history(page).getByRole('alert')).toBeVisible()
    await expect(page.getByRole('article')).toHaveCount(0)
    await expect(page.getByText('5 of 5 answers generated')).toHaveCount(0)
  })
test('cancellation needs acknowledgment and disables repeat submission', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const pending = gate()
  state.mutation = async (route) => {
    await pending.wait
    state.rows = [{ ...job, status: 'cancelled' }]
    return json(route, { ...job, status: 'cancelled' })
  }
  await open(page)
  await confirm(page, 'Cancel job')
  await expect(
    page.getByRole('alertdialog').getByRole('button', { name: 'Working…' })
  ).toBeDisabled()
  await expect(page.getByText('Job cancelled.')).toHaveCount(0)
  await expect
    .poll(
      () =>
        calls.filter(
          (c) => c.method === 'POST' && c.pathname.endsWith('/cancel')
        ).length
    )
    .toBe(1)
  pending.release()
  await expect(history(page).getByText('Job cancelled.')).toBeVisible()
  await expect(
    history(page).getByText('Cancelled', { exact: true })
  ).toBeVisible()
})
test('retry confirms charge uncertainty and only then shows the acknowledged queued attempt', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = [{ ...job, status: 'failed', retries_exhausted: true }]
  await open(page)
  await expect(page.getByText('Automatic retry limit reached.')).toBeVisible()
  await page.getByRole('button', { name: 'Retry job' }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toContainText('may have been charged')
  await dialog.getByRole('button', { name: 'Retry job' }).click()
  await expect(
    history(page).getByText('Another attempt is queued.')
  ).toBeVisible()
  await expect(history(page).getByText('Queued', { exact: true })).toBeVisible()
})
for (const status of [403, 404, 409, 500, 200])
  test(`failed or malformed mutation ${status} never announces success`, async ({
    page,
  }) => {
    const { state, calls } = await setup(page)
    state.mutation = (route) =>
      json(
        route,
        status === 200
          ? { ...job, id: 42, status: 'cancelled' }
          : { detail: 'PRIVATE_MUTATION' },
        status
      )
    await open(page)
    await confirm(page, 'Cancel job')
    await expect(history(page).getByRole('alert')).toBeVisible()
    await expect(
      history(page).getByText('Running', { exact: true })
    ).toBeVisible()
    if (status === 403) {
      await expect
        .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
        .toBe(2)
      await expect(
        page.getByRole('button', { name: 'Cancel job' })
      ).toHaveCount(0)
    }
    await expect(page.getByText('Job cancelled.')).toHaveCount(0)
    await expect(page.locator('body')).not.toContainText('PRIVATE_MUTATION')
  })
test('mutation401 invalidates cached history without false success', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.mutation = (route) => json(route, { detail: 'PRIVATE_DENIAL' }, 401)
  await open(page)
  await confirm(page, 'Cancel job')
  await expect(history(page).getByRole('alert')).toBeVisible()
  await expect(page.getByRole('article')).toHaveCount(0)
  await expect(
    page.getByRole('link', { name: 'Open questionnaire' })
  ).toHaveCount(0)
  await expect(page.getByText('Job cancelled.')).toHaveCount(0)
})
test('mutation403 hides rows until history confirms continued read-only access', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  await open(page)
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toBeVisible()
  const pending = gate()
  state.readWait = pending.wait
  state.mutation = (route) => json(route, { detail: 'PRIVATE_DENIAL' }, 403)
  await confirm(page, 'Cancel job')
  await expect
    .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
    .toBe(2)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.locator('article')).toHaveCount(0)
  await expect(
    page.getByRole('link', { name: 'Open questionnaire' })
  ).toHaveCount(0)
  pending.release()
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toBeVisible()
  await expect(
    page.getByRole('link', { name: 'Open questionnaire' })
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel job' })).toHaveCount(0)
  await expect(page.getByText('Job cancelled.')).toHaveCount(0)
})
for (const status of [403, 404, 500])
  test(`mutation403 followed by history${status} does not restore cached data`, async ({
    page,
  }) => {
    const { state, calls } = await setup(page)
    state.mutation = (route) => {
      state.readStatus = status
      return json(route, { detail: 'PRIVATE_DENIAL' }, 403)
    }
    await open(page)
    await confirm(page, 'Cancel job')
    await expect
      .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
      .toBe(2)
    await expect(page.getByRole('article')).toHaveCount(0)
    await expect(
      page.getByRole('link', { name: 'Open questionnaire' })
    ).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Cancel job' })).toHaveCount(
      0
    )
    await expect(page.getByText('Job cancelled.')).toHaveCount(0)
  })
test('acknowledged action and failed history reload show an explicit partial result', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.mutation = (route) => {
    state.readStatus = 500
    return json(route, { ...job, status: 'cancelled' })
  }
  await open(page)
  await confirm(page, 'Cancel job')
  await expect(history(page).getByText('Job cancelled.')).toBeVisible()
  await expect(history(page).getByText(/last confirmed results/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry job' })).toBeDisabled()
})
for (const role of ['admin', 'editor', 'reviewer', 'custom-denied'])
  test(`current ${role} capabilities guard reads and actions`, async ({
    page,
  }) => {
    const { calls } = await setup(page, role)
    await open(page)
    if (role === 'custom-denied') {
      await expect(page.getByText('Job access is restricted')).toBeVisible()
      expect(
        calls.filter((c) => c.pathname.startsWith('/api/jobs'))
      ).toHaveLength(0)
    } else
      await expect(
        page.getByRole('article', { name: 'Generate answers' })
      ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Cancel job' })).toHaveCount(
      role === 'admin' ? 1 : 0
    )
  })
test('late history and saved cursor cannot leak across a workspace switch', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const pending = gate()
  state.readWait = pending.wait
  await open(page, '?workspace_id=7&before_id=42')
  await expect
    .poll(() => calls.filter((c) => c.pathname === '/api/jobs').length)
    .toBe(1)
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(
    page.getByRole('article', { name: 'Export questionnaire' })
  ).toBeVisible()
  pending.release()
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toHaveCount(0)
  expect(calls.filter((c) => c.pathname === '/api/jobs').at(-1)?.search).toBe(
    '?workspace_id=8&limit=25'
  )
})
test('invalid saved cursor exposes a reset without a business request', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await open(page, '?workspace_id=7&before_id=PRIVATE_CURSOR')
  await expect(page.getByText('This history page is unavailable')).toBeVisible()
  expect(calls.filter((c) => c.pathname === '/api/jobs')).toHaveLength(0)
  await expect(page.locator('body')).not.toContainText('PRIVATE_CURSOR')
  await page.getByRole('button', { name: 'Newest jobs' }).click()
  await expect(
    page.getByRole('article', { name: 'Generate answers' })
  ).toBeVisible()
})
for (const width of [360, 768, 1440])
  test(`jobs page and dialog keyboard/axe at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await setup(page)
    await open(page)
    await expect(page.getByText('2 of 5 answers generated')).toBeVisible()
    const evidence = path.resolve('../../artifacts/acceptance/TC-15-038b')
    mkdirSync(path.join(evidence, 'screenshots'), { recursive: true })
    async function audit(surface: string) {
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth
        )
      ).toBe(true)
      const result = await new AxeBuilder({ page }).analyze()
      const violations = result.violations.map((item) => ({
        id: item.id,
        impact: item.impact,
        nodes: item.nodes.length,
      }))
      const axePath = path.join(evidence, `axe-${surface}-${width}.json`)
      writeFileSync(
        axePath,
        JSON.stringify(
          { width, surface, violationCount: violations.length, violations },
          null,
          2
        )
      )
      await testInfo.attach(`axe-${surface}-${width}`, {
        path: axePath,
        contentType: 'application/json',
      })
      const screenshot = path.join(
        evidence,
        'screenshots',
        `${surface}-${width}.png`
      )
      await page.screenshot({ path: screenshot, fullPage: true })
      await testInfo.attach(`${surface}-${width}`, {
        path: screenshot,
        contentType: 'image/png',
      })
      expect(violations).toEqual([])
    }
    await audit('page')
    const trigger = page.getByRole('button', { name: 'View details' })
    await trigger.focus()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: 'Job details' })
    await expect(dialog.getByText('3 of 5 answers generated')).toBeVisible()
    for (let index = 0; index < 7; index++) {
      await page.keyboard.press('Tab')
      expect(
        await dialog.evaluate((node) => node.contains(document.activeElement))
      ).toBe(true)
    }
    await audit('dialog')
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeFocused()
  })
