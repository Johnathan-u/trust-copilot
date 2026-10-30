import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Synthetic API fixtures qualify browser control paths, not API/provider integration.
const request = {
  id: 11,
  workspace_id: 7,
  assignee_id: null,
  requester_email: 'buyer@example.com',
  requester_name: 'Synthetic Buyer',
  subject: 'Security questions',
  message: 'Please review our security questions.',
  display_id: 'TR-11',
  frameworks: [],
  subject_areas: [],
  status: 'new',
  attachment_filename: 'questions.txt',
  attachment_storage_key: 'must-not-be-used',
  attachment_size: 19,
  submitted_host: null,
  submitted_path: null,
  resolution_method: 'slug',
  created_at: '2026-10-01T12:00:00Z',
  deleted_at: null,
}
const draft = {
  id: 21,
  trust_request_id: 11,
  author_id: 42,
  note_type: 'reply',
  body: 'Synthetic saved response.',
  body_revision: 1,
  approved_revision: null as number | null,
  approved_by: null as number | null,
  approved_at: null as string | null,
  delivery_status: 'draft',
  delivery_attempts: 0,
  delivery_started_at: null as string | null,
  delivery_accepted_at: null as string | null,
  delivery_error: null,
  created_at: '2026-10-01T12:00:00Z',
  author_email: 'reviewer@example.com',
  author_display_name: 'Synthetic Reviewer',
}
// Exact fields from the real _note_to_dict serializer for an internal note
// with no author: NOTE_TYPE_INTERNAL is internal_note, never internal.
const internalNote = {
  id: 31,
  trust_request_id: 11,
  author_id: null,
  note_type: 'internal_note',
  body: 'Synthetic internal review note.',
  body_revision: 1,
  approved_revision: null,
  approved_by: null,
  approved_at: null,
  delivery_status: null,
  delivery_attempts: null,
  delivery_started_at: null,
  delivery_accepted_at: null,
  delivery_error: null,
  created_at: null,
}
type Note = Omit<typeof draft, 'author_email' | 'author_display_name'> & {
  author_email?: string
  author_display_name?: string
}
function json(route: Route, value: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(value),
  })
}
async function installApi(page: Page, role = 'reviewer', canReview = true) {
  const state = {
    workspace: 7,
    rows: [request],
    notes: [{ ...draft }] as Note[],
    listStatus: 200,
    detailStatus: 200,
    notesStatus: 200,
    mutationStatus: 200,
    attachmentStatus: 200,
    outcome: 'accepted',
    calls: [] as {
      method: string
      path: string
      body: Record<string, unknown>
    }[],
  }
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const p = url.pathname
    const method = route.request().method()
    if (p === '/api/auth/me')
      return json(route, {
        id: 42,
        email: 'reviewer@example.com',
        display_name: 'Synthetic Reviewer',
        workspace_id: state.workspace,
        workspace_name: `Workspace ${state.workspace}`,
        workspace_slug: `workspace-${state.workspace}`,
        role,
        workspaces: [7, 8].map((id) => ({
          id,
          name: `Workspace ${id}`,
          slug: `workspace-${id}`,
          role,
        })),
        permissions: {
          can_edit: role === 'admin' || role === 'editor',
          can_admin: role === 'admin',
          can_review: canReview,
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
    if (p === '/api/auth/switch-workspace') {
      state.workspace = route.request().postDataJSON().workspace_id
      return json(route, {
        workspace_id: state.workspace,
        workspace_name: `Workspace ${state.workspace}`,
        workspace_slug: `workspace-${state.workspace}`,
        role,
      })
    }
    if (p === '/api/auth/alerts') return json(route, { alerts: [] })
    if (p.includes('/in-app-notifications/unread-count'))
      return json(route, { count: 0 })
    if (!p.startsWith('/api/trust-requests')) return json(route, {})
    const body = method === 'GET' ? {} : route.request().postDataJSON()
    state.calls.push({ method, path: p, body })
    if (p === '/api/trust-requests') {
      expect(url.searchParams.get('workspace_id')).toBe(String(state.workspace))
      return json(
        route,
        state.workspace === 7 ? state.rows : [],
        state.listStatus
      )
    }
    if (p.endsWith('/attachment'))
      return route.fulfill({
        status: state.attachmentStatus,
        contentType: 'application/octet-stream',
        body: 'Synthetic attachment',
      })
    if (p.endsWith('/notes')) return json(route, state.notes, state.notesStatus)
    if (p === '/api/trust-requests/11')
      return json(route, request, state.detailStatus)
    if (state.mutationStatus !== 200)
      return json(
        route,
        { detail: 'Rejected synthetic action' },
        state.mutationStatus
      )
    if (p.endsWith('/replies')) {
      expect(body).toEqual({ body: expect.any(String) })
      const saved = { ...draft, id: 22, body: body.body }
      state.notes.push(saved)
      return json(route, saved)
    }
    const note = state.notes.find((item) => p.includes(`/replies/${item.id}`))
    if (!note) return json(route, {}, 404)
    if (body.revision !== note.body_revision) return json(route, {}, 409)
    if (method === 'PATCH')
      Object.assign(note, {
        body: body.body,
        body_revision: note.body_revision + 1,
        approved_revision: null,
        approved_by: null,
        approved_at: null,
        delivery_status: 'draft',
      })
    else if (p.endsWith('/approve'))
      Object.assign(note, {
        approved_revision: note.body_revision,
        approved_by: 42,
        approved_at: '2026-10-01T13:00:00Z',
        delivery_status: 'approved',
      })
    else if (p.endsWith('/send')) {
      expect(body).toEqual({ revision: note.body_revision })
      expect(note.approved_revision).toBe(note.body_revision)
      Object.assign(note, { delivery_status: state.outcome })
    } else return json(route, {}, 404)
    return json(route, note)
  })
  return state
}
async function openRequest(page: Page) {
  await page.goto('/dashboard/trust-requests')
  await page.getByRole('button', { name: /Security questions/ }).click()
  await expect(page.getByLabel('Reply 21 text')).toBeVisible()
}
async function approve(page: Page) {
  await page.getByLabel(/I reviewed saved revision/).check()
  await page.getByRole('button', { name: 'Approve revision' }).click()
  await expect(
    page.getByRole('button', { name: 'Send approved reply' })
  ).toBeEnabled()
}

test('saved draft, edited revision and approved send use separate acknowledged actions', async ({
  page,
}) => {
  const state = await installApi(page)
  await openRequest(page)
  await page.getByLabel('Reply text', { exact: true }).fill('A new draft.')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.getByLabel('Reply 22 text')).toHaveValue('A new draft.')
  await expect(page.getByLabel('Reply text', { exact: true })).toHaveValue('')
  const reply = page.getByRole('article', { name: 'Reply 21', exact: true })
  await reply.getByLabel(/I reviewed saved revision/).check()
  await reply.getByRole('button', { name: 'Approve revision' }).click()
  await reply.getByLabel('Reply 21 text').fill('An edited answer.')
  await expect(
    reply.getByRole('button', { name: 'Send approved reply' })
  ).toBeDisabled()
  await reply.getByLabel(/I reviewed saved revision/).check()
  await reply.getByRole('button', { name: 'Save new revision' }).click()
  await expect(
    reply.getByText('Draft — approval required', { exact: true })
  ).toBeVisible()
  await reply.getByLabel(/I reviewed saved revision/).check()
  await reply.getByRole('button', { name: 'Approve revision' }).click()
  await reply.getByRole('button', { name: 'Send approved reply' }).click()
  await expect(
    reply.getByText(/Provider accepted — recipient delivery not confirmed/)
  ).toBeVisible()
  await expect(
    reply.getByRole('button', { name: 'Send approved reply' })
  ).toHaveCount(0)
  expect(state.calls.filter((c) => c.path.endsWith('/send'))).toEqual([
    {
      method: 'POST',
      path: '/api/trust-requests/11/replies/21/send',
      body: { revision: 2 },
    },
  ])
  await page.reload()
  await page.getByRole('button', { name: /Security questions/ }).click()
  await expect(page.getByLabel('Reply 21 text')).toHaveValue(
    'An edited answer.'
  )
  await expect(
    page.getByText(/Provider accepted — recipient delivery not confirmed/)
  ).toBeVisible()
})
for (const status of [403, 404, 409, 500]) {
  test(`rejected ${status} save retains text and refresh requires review of the latest revision`, async ({
    page,
  }) => {
    const state = await installApi(page)
    await openRequest(page)
    await page.getByLabel('Reply 21 text').fill('Keep my unsaved answer.')
    await page.getByLabel(/I reviewed saved revision/).check()
    state.mutationStatus = status
    await page.getByRole('button', { name: 'Save new revision' }).click()
    await expect(page.locator('#main-content').getByRole('alert')).toBeVisible()
    await expect(page.getByLabel('Reply 21 text')).toHaveValue(
      'Keep my unsaved answer.'
    )
    await expect(
      page.getByRole('button', { name: 'Save new revision' })
    ).toBeDisabled()
    state.mutationStatus = 200
    Object.assign(state.notes[0], {
      body: 'Another reviewer changed this.',
      body_revision: 2,
    })
    await page.getByRole('button', { name: 'Reload saved replies' }).click()
    await expect(page.getByLabel('Reply 21 text')).toHaveValue(
      'Keep my unsaved answer.'
    )
    await expect(
      page.getByText('Another reviewer changed this.', { exact: true })
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Save new revision' })
    ).toBeDisabled()
    await page.getByLabel(/I reviewed saved revision 2/).check()
    await page.getByRole('button', { name: 'Save new revision' }).click()
    await expect(
      page.getByRole('heading', { name: 'Reply · revision 3' })
    ).toBeVisible()
  })
}
for (const outcome of ['uncertain', 'sending', 'unavailable']) {
  test(`${outcome} is truthful and does not trigger an automatic or blind repeat send`, async ({
    page,
  }) => {
    const state = await installApi(page)
    state.outcome = outcome
    await openRequest(page)
    await approve(page)
    await page.getByRole('button', { name: 'Send approved reply' }).click()
    await expect(
      page.getByText(
        outcome === 'uncertain'
          ? 'Delivery outcome unknown — do not resend'
          : outcome === 'sending'
            ? 'Sending recorded — outcome pending; do not resend'
            : 'Delivery unavailable — provider was not called',
        { exact: true }
      )
    ).toBeVisible()
    if (outcome === 'unavailable')
      await expect(
        page.getByRole('button', { name: 'Send approved reply' })
      ).toBeDisabled()
    else
      await expect(
        page.getByRole('button', { name: 'Send approved reply' })
      ).toHaveCount(0)
    expect(state.calls.filter((c) => c.path.endsWith('/send'))).toHaveLength(1)
  })
}
for (const role of [
  'admin',
  'editor',
  'reviewer',
  'custom-reviewer',
  'custom-denied',
]) {
  test(`${role} follows current can_review permission without invented roles`, async ({
    page,
  }) => {
    const state = await installApi(page, role, role !== 'custom-denied')
    await page.goto('/dashboard/trust-requests')
    if (role === 'custom-denied') {
      await expect(
        page.getByRole('heading', { name: 'Review access required' })
      ).toBeVisible()
      expect(state.calls).toHaveLength(0)
    } else {
      await page.getByRole('button', { name: /Security questions/ }).click()
      await expect(page.getByLabel('Reply 21 text')).toBeVisible()
    }
  })
}
test('download uses the protected attachment endpoint and surfaces denial', async ({
  page,
}) => {
  const state = await installApi(page)
  await openRequest(page)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Download attachment' }).click()
  expect((await download).suggestedFilename()).toBe('questions.txt')
  state.attachmentStatus = 403
  await page.getByRole('button', { name: 'Download attachment' }).click()
  await expect(page.locator('#main-content').getByRole('alert')).toContainText(
    'permission'
  )
  expect(state.calls.some((c) => c.path.includes('must-not-be-used'))).toBe(
    false
  )
})
test('empty, failed list, failed detail and partial notes have separate recovery states', async ({
  page,
}) => {
  const state = await installApi(page)
  state.listStatus = 500
  await page.goto('/dashboard/trust-requests')
  await expect(page.locator('#main-content').getByRole('alert')).toBeVisible()
  await expect(
    page.getByText('No incoming requests', { exact: true })
  ).toHaveCount(0)
  state.listStatus = 200
  state.rows = []
  await page.getByRole('button', { name: 'Refresh list' }).click()
  await expect(
    page.getByText('No incoming requests', { exact: true })
  ).toBeVisible()
  state.rows = [request]
  state.detailStatus = 404
  await page.getByRole('button', { name: 'Refresh list' }).click()
  await page.getByRole('button', { name: /Security questions/ }).click()
  await expect(
    page.getByRole('heading', { name: 'Request unavailable' })
  ).toBeVisible()
  state.detailStatus = 200
  state.notesStatus = 500
  await page.reload()
  await page.getByRole('button', { name: /Security questions/ }).click()
  await expect(
    page.getByText('Please review our security questions.', { exact: true })
  ).toBeVisible()
  await expect(page.locator('#main-content').getByRole('alert')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Save draft', exact: true })
  ).toBeDisabled()
  state.notesStatus = 200
  await page.getByRole('button', { name: 'Reload saved replies' }).click()
  await expect(page.getByLabel('Reply 21 text')).toBeVisible()
})
test('switching workspace clears private rows and ignores late old-workspace detail', async ({
  page,
}) => {
  await installApi(page)
  let release: (() => void) | undefined
  const wait = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/trust-requests/11', async (route) => {
    await wait
    await json(route, request)
  })
  await page.goto('/dashboard/trust-requests')
  await page.getByRole('button', { name: /Security questions/ }).click()
  await expect(
    page.getByText('Loading request…', { exact: true })
  ).toBeVisible()
  await page.locator('#sidebar-workspace-select').selectOption('8')
  await expect(
    page.getByText('No incoming requests', { exact: true })
  ).toBeVisible()
  release!()
  await expect(page.getByLabel('Reply 21 text')).toHaveCount(0)
  await expect(
    page.getByText('Please review our security questions.', { exact: true })
  ).toHaveCount(0)
})
for (const width of [360, 768, 1440]) {
  test(`incoming list and reply editor are keyboard accessible at ${width}px`, async ({
    page,
  }, testInfo) => {
    await installApi(page)
    await page.setViewportSize({ width, height: 900 })
    await openRequest(page)
    await page.getByLabel('Reply 21 text').focus()
    await page.keyboard.press('Tab')
    await expect(page.getByLabel(/I reviewed saved revision/)).toBeFocused()
    await page.keyboard.press('Space')
    await page.keyboard.press('Tab')
    await expect(
      page.getByRole('button', { name: 'Approve revision' })
    ).toBeFocused()
    const main = page.locator('#main-content')
    expect(await main.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
      true
    )
    const result = await new AxeBuilder({ page })
      .include('#main-content')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const violations = result.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    const dir = path.resolve('../../artifacts/acceptance/TC-15-039a')
    mkdirSync(path.join(dir, 'screenshots'), { recursive: true })
    const axePath = path.join(dir, `axe-incoming-${width}.json`)
    writeFileSync(
      axePath,
      JSON.stringify(
        {
          width,
          violationCount: violations.length,
          violations,
          violationDetails: result.violations,
        },
        null,
        2
      )
    )
    const screenshot = path.join(dir, 'screenshots', `incoming-${width}.png`)
    await page.screenshot({ path: screenshot, fullPage: true })
    await testInfo.attach(`incoming-${width}`, {
      path: screenshot,
      contentType: 'image/png',
    })
    await testInfo.attach(`axe-incoming-${width}`, {
      path: axePath,
      contentType: 'application/json',
    })
    expect(
      violations.filter((item) =>
        ['critical', 'serious'].includes(item.impact || '')
      )
    ).toEqual([])
  })
}

test('unconfirmed new draft stays editable and cannot be submitted twice without inspection', async ({
  page,
}) => {
  const state = await installApi(page)
  await openRequest(page)
  state.mutationStatus = 500
  await page
    .getByLabel('Reply text', { exact: true })
    .fill('Keep this draft after rejection.')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page.locator('#main-content').getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('Reply text', { exact: true })).toHaveValue(
    'Keep this draft after rejection.'
  )
  await expect(
    page.getByRole('button', { name: 'Save draft', exact: true })
  ).toBeDisabled()
  expect(
    state.calls.filter(
      (call) => call.method === 'POST' && call.path.endsWith('/replies')
    )
  ).toHaveLength(1)
})
test('lost send response blocks repetition until authoritative saved state is reloaded', async ({
  page,
}) => {
  const state = await installApi(page)
  await openRequest(page)
  await approve(page)
  let attempts = 0
  await page.route(
    '**/api/trust-requests/11/replies/21/send',
    async (route) => {
      attempts += 1
      state.notes[0].delivery_status = 'accepted'
      await route.abort('failed')
    }
  )
  await page.getByRole('button', { name: 'Send approved reply' }).click()
  await expect(page.locator('#main-content').getByRole('alert')).toContainText(
    'not confirmed'
  )
  await expect(
    page.getByRole('button', { name: 'Send approved reply' })
  ).toBeDisabled()
  await page.getByRole('button', { name: 'Reload saved replies' }).click()
  await expect(
    page.getByText(/Provider accepted — recipient delivery not confirmed/)
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Send approved reply' })
  ).toHaveCount(0)
  expect(attempts).toBe(1)
})

test('backend internal notes remain visible beside actionable replies', async ({
  page,
}) => {
  const state = await installApi(page)
  state.notes.push(internalNote)
  await openRequest(page)
  const internal = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: 'Internal note', exact: true }),
  })
  await expect(internal).toContainText('Synthetic internal review note.')
  await expect(internal.getByRole('textbox')).toHaveCount(0)
  await expect(internal.getByRole('button')).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Approve revision' })
  ).toBeVisible()
  await expect(page.locator('#main-content').getByRole('alert')).toHaveCount(0)
})
