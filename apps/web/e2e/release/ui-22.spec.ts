import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

test.use({ storageState: { cookies: [], origins: [] } })

test('legacy bookmark is a server redirect with no approved query parameters', async ({
  request,
}) => {
  const response = await request.get(
    '/dashboard/vendor-requests?status=pending&status=completed&token=private-token&next=https%3A%2F%2Fexample.com',
    {
      headers: { Cookie: 'tc_session=synthetic-session' },
      maxRedirects: 0,
    }
  )
  expect(response.status()).toBe(307)
  const destination = new URL(response.headers().location, response.url())
  expect(destination.origin).toBe(new URL(response.url()).origin)
  expect(destination.pathname).toBe('/dashboard/requests')
  expect(destination.search).toBe('')
  expect(destination.hash).toBe('')
})

const record = {
  schema_version: '1',
  id: 41,
  workspace_id: 7,
  vendor_email: 'vendor@example.com',
  questionnaire_id: 999,
  message: null,
  status: 'pending',
  link_token: null,
  delivery_status: 'not_sent',
  last_delivery_error: null,
  created_at: '2026-10-01T12:00:00Z',
  expires_at: '2099-01-01T12:00:00Z',
  revoked_at: null,
  last_delivery_at: null,
  submitted_at: null,
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
    rows: [record],
    readStatus: 200,
    questionnaireStatus: 200,
    readWait: Promise.resolve(),
    questionnaireName: 'Vendor questionnaire',
    mutation: async (route: Route) => json(route, record),
  }
  const calls: Array<{
    path: string
    method: string
    key?: string
    body: unknown
  }> = []
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
    const p = new URL(request.url()).pathname
    const method = request.method()
    calls.push({
      path: p,
      method,
      key: request.headers()['idempotency-key'],
      body: request.postDataJSON(),
    })
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
        can_review: role !== 'viewer',
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
    if (p === '/api/vendor-requests' && method === 'GET') {
      const snapshot =
        state.workspace === 7
          ? state.rows
          : [
              {
                ...record,
                id: 81,
                workspace_id: 8,
                vendor_email: 'current@example.com',
              },
            ]
      const status = state.readStatus
      await state.readWait
      // A workspace switch aborts its previous fetch; a late reply is deliberately ignored.
      return json(
        route,
        status === 200 ? snapshot : { detail: 'Synthetic read failure' },
        status
      ).catch(() => {})
    }
    if (p.startsWith('/api/vendor-requests') && method !== 'GET')
      return state.mutation(route)
    if (p === '/api/questionnaires')
      return json(
        route,
        state.questionnaireStatus === 200
          ? [
              {
                id: 999,
                filename: state.questionnaireName,
                status: 'completed',
              },
            ]
          : { detail: 'Synthetic questionnaire failure' },
        state.questionnaireStatus
      )
    if (p.endsWith('/unread-count')) return json(route, { count: 0 })
    if (p === '/api/auth/alerts') return json(route, { alerts: [] })
    if (p === '/api/dashboard/cards')
      return json(route, { cards: [], has_custom: false })
    if (p === '/api/dashboard/cards/allowed-routes')
      return json(route, {
        routes: ['/dashboard/requests'],
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
async function open(page: Page) {
  await page.goto('/dashboard/vendor-requests')
  await expect(page).toHaveURL(/\/dashboard\/requests$/)
  await expect(
    page.getByRole('heading', { name: 'Requests', exact: true })
  ).toBeVisible()
}
async function create(page: Page) {
  await page
    .getByRole('button', { name: 'Create Request', exact: true })
    .click()
  const dialog = page.getByRole('dialog', {
    name: 'Create Request',
    exact: true,
  })
  await dialog.getByLabel('Vendor Email').fill('new@example.com')
  await dialog.getByRole('button', { name: 'Create Link', exact: true }).click()
}

test('bookmark navigation commits only the destination and Back returns to the preceding page', async ({
  page,
}) => {
  const { calls } = await setup(page)
  await page.goto('/dashboard')
  await expect(
    page.getByRole('heading', { name: 'Dashboard', exact: true })
  ).toBeVisible()
  const navigations: string[] = []
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame())
      navigations.push(new URL(frame.url()).pathname)
  })
  await open(page)
  await expect(
    page.getByText('vendor@example.com', { exact: true })
  ).toBeVisible()
  expect(navigations).toEqual(['/dashboard/requests'])
  expect(
    calls.filter((call) => call.path === '/api/vendor-requests')
  ).toHaveLength(1)
  expect(
    calls.filter((call) => /analytics|page.?view/.test(call.path))
  ).toHaveLength(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/dashboard$/)
})

for (const role of ['reviewer', 'viewer']) {
  test(`${role} gets the actual read permission without administrator actions`, async ({
    page,
  }) => {
    const { calls } = await setup(page, role)
    await open(page)
    if (role === 'reviewer')
      await expect(
        page.getByText('vendor@example.com', { exact: true })
      ).toBeVisible()
    else {
      await expect(
        page.getByText('You need review access to view requests.')
      ).toBeVisible()
      expect(
        calls.filter((call) => call.path === '/api/vendor-requests')
      ).toHaveLength(0)
    }
    await expect(
      page.getByRole('button', { name: 'Create Request', exact: true })
    ).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: /send invitation/i })
    ).toHaveCount(0)
  })
}

test('empty requests remain an honest empty state with an available create action', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = []
  await open(page)
  await expect(page.getByText('No requests yet')).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Create First Request' })
  ).toBeEnabled()
})

test('list failure remains an error and retry obtains the acknowledged list', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.readStatus = 500
  await open(page)
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toBeVisible()
  await expect(page.getByText('No requests yet')).toHaveCount(0)
  state.readStatus = 200
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(
    page.getByText('vendor@example.com', { exact: true })
  ).toBeVisible()
})

test('questionnaire failure retains requests and does not display internal ids', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.questionnaireStatus = 503
  await open(page)
  await expect(
    page.getByText('vendor@example.com', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Questionnaire unavailable')).toBeVisible()
  await expect(page.getByText('#999', { exact: true })).toHaveCount(0)
})

test('delayed create and its null-token replay do not fabricate a link or early success', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const delayed = gate()
  state.mutation = async (route) => {
    await delayed.wait
    return json(route, { ...record, id: 42, vendor_email: 'new@example.com' })
  }
  await open(page)
  await create(page)
  await expect(page.getByRole('button', { name: 'Creating...' })).toBeDisabled()
  await expect(
    page.getByRole('dialog', { name: 'Request Created' })
  ).toHaveCount(0)
  await expect
    .poll(
      () =>
        calls.filter(
          (call) =>
            call.method === 'POST' && call.path === '/api/vendor-requests'
        ).length
    )
    .toBe(1)
  expect(
    calls.find(
      (call) => call.path === '/api/vendor-requests' && call.method === 'POST'
    )?.key
  ).toBeTruthy()
  delayed.release()
  const dialog = page.getByRole('dialog', { name: 'Request Created' })
  await expect(dialog.getByText(/one-time link is not available/)).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Copy', exact: true })
  ).toHaveCount(0)
  await expect(dialog).not.toContainText('undefined')
})

test('creation exposes only the returned one-time link and copy waits for clipboard acknowledgment', async ({
  page,
  context,
}) => {
  const { state } = await setup(page)
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  state.mutation = (route) =>
    json(route, {
      ...record,
      id: 42,
      link_token: 'synthetic-once',
      share_url: '/vendor-response?token=synthetic-once',
    })
  await open(page)
  await create(page)
  const dialog = page.getByRole('dialog', { name: 'Request Created' })
  await expect(
    dialog.getByText(/vendor-response\?token=synthetic-once/)
  ).toBeVisible()
  await dialog.getByRole('button', { name: 'Copy', exact: true }).click()
  await expect(dialog.getByRole('button', { name: 'Copied!' })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    '/vendor-response?token=synthetic-once'
  )
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByRole('button', { name: 'Copy Link' })).toHaveCount(0)
})

test('progress rejection keeps the current state and reports the server failure', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.mutation = (route) =>
    json(
      route,
      { detail: 'Completion requires a submitted vendor response.' },
      409
    )
  await open(page)
  const progress = page.getByRole('combobox', { name: /Update progress/ })
  await expect(progress.locator('option[value="completed"]')).toHaveCount(0)
  await progress.selectOption('in_progress')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('Pending', { exact: true })).toBeVisible()
})

test('send retry preserves its key after a network failure and only confirms provider acceptance', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  state.mutation = (route) => route.abort('failed')
  await open(page)
  await page.getByRole('button', { name: 'Send invitation' }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  state.mutation = (route) =>
    json(route, { ...record, delivery_status: 'accepted' })
  await page.getByRole('button', { name: 'Send invitation' }).click()
  await expect(page.getByText('Accepted by email provider')).toBeVisible()
  const attempts = calls.filter((call) => call.path.endsWith('/send'))
  expect(attempts).toHaveLength(2)
  expect(attempts[0].key).toBeTruthy()
  expect(attempts[1].key).toBe(attempts[0].key)
  state.mutation = (route) =>
    json(route, {
      ...record,
      delivery_status: 'accepted',
      link_token: 'rotated-once',
      share_url: '/vendor-response?token=rotated-once',
    })
  await page.getByRole('button', { name: 'Resend invitation' }).click()
  await expect(
    page.getByRole('dialog', { name: 'Invitation result' })
  ).toContainText('rotated-once')
  expect(calls.find((call) => call.path.endsWith('/resend'))?.key).toBeTruthy()
})

test('simultaneous row invitations preserve each one-time link until its result is closed', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const second = {
    ...record,
    id: 42,
    vendor_email: 'second@example.com',
    delivery_status: 'accepted',
  }
  state.rows = [record, second]
  const delayed = gate()
  state.mutation = async (route) => {
    const first = new URL(route.request().url()).pathname.endsWith('/41/send')
    if (first) await delayed.wait
    const token = first ? 'first-one-time-token' : 'second-one-time-token'
    return json(route, {
      ...(first ? record : second),
      delivery_status: 'accepted',
      link_token: token,
      share_url: `/vendor-response?token=${token}`,
    })
  }
  await open(page)
  await expect(
    page.getByText('second@example.com', { exact: true })
  ).toBeVisible()
  // Dispatch both rows synchronously, including repeated clicks, so the guard
  // must protect the request before disabled controls finish rendering.
  await page
    .getByRole('region', { name: 'Outbound requests' })
    .evaluate((region) => {
      const buttons = [...region.querySelectorAll('button')].filter((button) =>
        /^(Send|Resend) invitation$/.test(button.textContent?.trim() ?? '')
      )
      for (const button of buttons) {
        button.click()
        button.click()
      }
    })
  const invitationCalls = () =>
    calls.filter((call) => /\/(send|resend)$/.test(call.path))
  await expect.poll(() => invitationCalls().length).toBe(1)
  await expect(
    page.getByRole('button', { name: 'Resend invitation' })
  ).toBeDisabled()
  await expect(
    page.getByRole('button', { name: 'Create Request', exact: true })
  ).toBeDisabled()
  delayed.release()
  const result = page.getByRole('dialog', { name: 'Invitation result' })
  await expect(result).toContainText('first-one-time-token')
  await expect(result).not.toContainText('second-one-time-token')
  const secondRow = page
    .getByRole('row', { includeHidden: true })
    .filter({ hasText: 'second@example.com' })
  await expect(
    secondRow.getByRole('button', {
      name: 'Resend invitation',
      includeHidden: true,
    })
  ).toBeDisabled()
  expect(invitationCalls()).toHaveLength(1)
  await result.getByRole('button', { name: 'Close', exact: true }).click()
  await secondRow.getByRole('button', { name: 'Resend invitation' }).click()
  await expect(result).toContainText('second-one-time-token')
  expect(invitationCalls().map((call) => call.path)).toEqual([
    '/api/vendor-requests/41/send',
    '/api/vendor-requests/42/resend',
  ])
  await result.getByRole('button', { name: 'Done' }).click()
  await expect(
    secondRow.getByRole('button', { name: 'Resend invitation' })
  ).toBeEnabled()
})

for (const [delivery, label] of [
  ['unavailable', 'Email delivery unavailable'],
  ['uncertain', 'Delivery outcome unknown'],
  ['sending', 'Delivery awaiting confirmation'],
]) {
  test(`${delivery} never appears as accepted or delivered`, async ({
    page,
  }) => {
    const { state } = await setup(page)
    state.rows = [{ ...record, delivery_status: delivery }]
    await open(page)
    await expect(page.getByText(label)).toBeVisible()
    await expect(page.getByText('Accepted by email provider')).toHaveCount(0)
    if (delivery !== 'unavailable')
      await expect(
        page.getByRole('button', { name: /send invitation/i })
      ).toHaveCount(0)
  })
}

test('revoke requires confirmation and an acknowledged response before displaying revoked', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const delayed = gate()
  state.mutation = async (route) => {
    await delayed.wait
    return json(route, {
      ...record,
      status: 'revoked',
      revoked_at: '2026-10-30T12:00:00Z',
    })
  }
  await open(page)
  await page.getByRole('button', { name: 'Revoke link' }).click()
  expect(calls.filter((call) => call.path.endsWith('/revoke'))).toHaveLength(0)
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Revoke link' })
    .click()
  await expect(
    page.getByRole('alertdialog').getByRole('button', { name: 'Working…' })
  ).toBeDisabled()
  delayed.release()
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  await expect(page.getByText('Revoked', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: /send invitation/i })
  ).toHaveCount(0)
})

test('only recorded submission presents completed state, while an expired grant remains explicit', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = [
    {
      ...record,
      status: 'completed',
      submitted_at: '2026-10-30T12:00:00Z',
    } as typeof record,
    {
      ...record,
      id: 42,
      vendor_email: 'expired@example.com',
      status: 'expired',
      expires_at: '2020-01-01T00:00:00Z',
    },
  ]
  await open(page)
  const completed = page
    .getByRole('row')
    .filter({ hasText: 'vendor@example.com' })
  await expect(completed.getByText('Completed', { exact: true })).toBeVisible()
  await expect(completed.getByRole('combobox')).toHaveCount(0)
  await expect(page.getByText('Expired', { exact: true })).toBeVisible()
})

test('late old-workspace reads cannot replace the new workspace list', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const delayed = gate()
  state.readWait = delayed.wait
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await expect
    .poll(
      () => calls.filter((call) => call.path === '/api/vendor-requests').length
    )
    .toBe(1)
  state.readWait = Promise.resolve()
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(
    page.getByText('current@example.com', { exact: true })
  ).toBeVisible()
  delayed.release()
  await expect(
    page.getByText('vendor@example.com', { exact: true })
  ).toHaveCount(0)
})

test('late old-workspace send cannot show its token or result in the new workspace', async ({
  page,
}) => {
  const { state, calls } = await setup(page)
  const delayed = gate()
  state.mutation = async (route) => {
    await delayed.wait
    return json(route, {
      ...record,
      delivery_status: 'accepted',
      link_token: 'old-workspace-token',
      share_url: '/vendor-response?token=old-workspace-token',
    })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await page.getByRole('button', { name: 'Send invitation' }).click()
  await expect
    .poll(() => calls.filter((call) => call.path.endsWith('/send')).length)
    .toBe(1)
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(
    page.getByText('current@example.com', { exact: true })
  ).toBeVisible()
  const reply = page.waitForResponse((response) =>
    response.url().endsWith('/api/vendor-requests/41/send')
  )
  delayed.release()
  await (await reply).finished()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      )
  )
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('old-workspace-token')
})

for (const width of [360, 768, 1440]) {
  test(`long content, keyboard dialog and accessibility at ${width}px`, async ({
    page,
  }, testInfo) => {
    const { state } = await setup(page)
    state.rows = [
      { ...record, vendor_email: `${'long'.repeat(16)}@example.com` },
    ]
    state.questionnaireName = 'Questionnaire'.repeat(24)
    await page.setViewportSize({ width, height: 900 })
    await open(page)
    await expect(
      page.getByRole('region', { name: 'Outbound requests' })
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    const trigger = page.getByRole('button', {
      name: 'Create Request',
      exact: true,
    })
    await trigger.focus()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', {
      name: 'Create Request',
      exact: true,
    })
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Vendor Email').fill('vendor@example.com')
    await dialog.getByLabel('Message').fill('Long instructions '.repeat(100))
    for (let i = 0; i < 9; i++) {
      await page.keyboard.press('Tab')
      expect(
        await dialog.evaluate((node) => node.contains(document.activeElement))
      ).toBe(true)
    }
    const evidenceDir = path.resolve('../../artifacts/acceptance/TC-15-024')
    mkdirSync(path.join(evidenceDir, 'screenshots'), { recursive: true })
    const axe = await new AxeBuilder({ page }).analyze()
    const violations = axe.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    const axePath = path.join(evidenceDir, `axe-dialog-${width}.json`)
    writeFileSync(
      axePath,
      JSON.stringify(
        { width, violationCount: violations.length, violations },
        null,
        2
      )
    )
    await testInfo.attach(`axe-dialog-${width}`, {
      path: axePath,
      contentType: 'application/json',
    })
    expect(
      violations.filter((item) =>
        ['critical', 'serious'].includes(item.impact || '')
      )
    ).toEqual([])
    const screenshot = path.join(
      evidenceDir,
      'screenshots',
      `requests-dialog-${width}.png`
    )
    await page.screenshot({ path: screenshot, fullPage: true })
    await testInfo.attach(`requests-dialog-${width}`, {
      path: screenshot,
      contentType: 'image/png',
    })
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeFocused()
    const tableAxe = await new AxeBuilder({ page }).analyze()
    const tableViolations = tableAxe.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    const tablePath = path.join(evidenceDir, `axe-list-${width}.json`)
    writeFileSync(
      tablePath,
      JSON.stringify(
        {
          width,
          violationCount: tableViolations.length,
          violations: tableViolations,
        },
        null,
        2
      )
    )
    await testInfo.attach(`axe-list-${width}`, {
      path: tablePath,
      contentType: 'application/json',
    })
    expect(
      tableViolations.filter((item) =>
        ['critical', 'serious'].includes(item.impact || '')
      )
    ).toEqual([])
    const tableScreenshot = path.join(
      evidenceDir,
      'screenshots',
      `requests-list-${width}.png`
    )
    await page.screenshot({ path: tableScreenshot, fullPage: true })
    await testInfo.attach(`requests-list-${width}`, {
      path: tableScreenshot,
      contentType: 'image/png',
    })
  })
}
