import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

test.use({ storageState: { cookies: [], origins: [] } })
const record = {
  schema_version: 'deals/v1',
  id: 41,
  workspace_id: 7,
  company_name: 'Synthetic Buyer',
  buyer_contact_name: 'Synthetic Contact',
  buyer_contact_email: 'buyer@example.com',
  deal_value_arr: '9999999999999999.99',
  currency: 'XTS',
  stage: 'evaluation',
  close_date: null,
  expected_close_date: '2026-12-31',
  actual_close_date: null,
  requested_frameworks: [],
  linked_questionnaire_ids: [],
  linked_document_ids: [],
  room_id: null,
  crm_source: null,
  crm_external_id: null,
  owner_user_id: null,
  notes: null,
  created_at: null,
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
    rows: [record] as unknown[],
    readStatus: 200,
    readBody: undefined as unknown,
    readWait: Promise.resolve(),
    switchWait: Promise.resolve(),
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
    const request = route.request(),
      p = new URL(request.url()).pathname,
      method = request.method()
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
        can_edit: ['admin', 'editor'].includes(role),
        can_review: ['admin', 'editor', 'reviewer'].includes(role),
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
      await state.switchWait
      state.workspace = request.postDataJSON().workspace_id
      return json(route, {
        ...me,
        workspace_id: state.workspace,
        workspace_name: 'Second workspace',
      })
    }
    if (p === '/api/deals' && method === 'GET') {
      const snapshot = state.readBody ?? {
        deals:
          state.workspace === 7
            ? state.rows
            : [{ ...record, workspace_id: 8, company_name: 'Current Buyer' }],
      }
      const status = state.readStatus
      await state.readWait
      return json(
        route,
        status === 200 ? snapshot : { detail: 'Synthetic read failure' },
        status
      ).catch(() => {})
    }
    if (p.startsWith('/api/deals') && method !== 'GET')
      return state.mutation(route)
    if (p.endsWith('/unread-count')) return json(route, { count: 0 })
    if (p === '/api/auth/alerts') return json(route, { alerts: [] })
    if (p === '/api/dashboard/cards')
      return json(route, { cards: [], has_custom: false })
    if (p === '/api/dashboard/cards/allowed-routes')
      return json(route, {
        routes: ['/dashboard/deals'],
        icons: ['document'],
        sizes: ['medium'],
        visibility_scopes: ['all'],
      })
    if (p === '/api/workspaces/creation-policy')
      return json(route, { can_create: false })
    return json(route, {})
  })
  return {
    state,
    calls,
    writes: () =>
      calls.filter(
        (call) => call.path.startsWith('/api/deals') && call.method !== 'GET'
      ),
  }
}
async function open(page: Page) {
  await page.goto('/dashboard/deals')
  await expect(
    page.getByRole('heading', { name: 'Deals', exact: true })
  ).toBeVisible()
}
function companyHeader(page: Page, company: string) {
  // Company and contact share the same row header. Match its complete accessible
  // name so populated contacts do not make exact company-only text disappear.
  return page
    .getByRole('region', { name: 'Deals list', exact: true })
    .getByRole('rowheader', {
      name: `${company} ${record.buyer_contact_name} · ${record.buyer_contact_email}`,
      exact: true,
    })
}
async function create(page: Page) {
  await page.getByRole('button', { name: 'Create deal', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Create deal', exact: true })
  await dialog.getByLabel('Company name').fill('New Buyer')
  return dialog
}
for (const role of ['editor', 'reviewer', 'custom_read', 'unconfigured']) {
  test(`session reader ${role} can read but cannot create or edit`, async ({
    page,
  }) => {
    await setup(page, role)
    await open(page)
    await expect(companyHeader(page, 'Synthetic Buyer')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Create deal' })).toHaveCount(
      0
    )
    await expect(
      page.getByRole('button', { name: /Edit Synthetic/ })
    ).toHaveCount(0)
  })
}
test('valid empty data offers creation without inventing a pipeline total', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.rows = []
  await open(page)
  await expect(
    page.getByRole('heading', { name: 'No deals yet' })
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Create deal' })).toBeVisible()
  await expect(page.getByText('$0')).toHaveCount(0)
})
for (const status of [401, 403, 404, 500]) {
  test(`failed list ${status} stays distinct from empty and supports retry`, async ({
    page,
  }) => {
    const { state } = await setup(page)
    state.readStatus = status
    await open(page)
    await expect(page.locator('[data-state="error"]')).toBeVisible()
    await expect(page.getByText('No deals yet')).toHaveCount(0)
    state.readStatus = 200
    await page.getByRole('button', { name: 'Try again' }).click()
    await expect(companyHeader(page, 'Synthetic Buyer')).toBeVisible()
  })
}
for (const [name, body] of [
  ['missing list', {}],
  [
    'partial malformed list',
    { deals: [record, { ...record, id: 42, stage: 'unknown' }] },
  ],
  ['foreign workspace', { deals: [{ ...record, workspace_id: 8 }] }],
] as const) {
  test(`rejects ${name} without a false empty or partial list`, async ({
    page,
  }) => {
    const { state } = await setup(page)
    state.readBody = body
    await open(page)
    await expect(
      page.getByText('The response could not be read. Try again.')
    ).toBeVisible()
    await expect(companyHeader(page, 'Synthetic Buyer')).toHaveCount(0)
    await expect(page.getByText('No deals yet')).toHaveCount(0)
  })
}
test('create preserves exact decimal strings and waits for acknowledgment plus authoritative reload', async ({
  page,
}) => {
  const { state, writes } = await setup(page),
    pending = gate()
  state.mutation = async (route) => {
    await pending.wait
    state.rows = [{ ...record, company_name: 'Server Buyer' }]
    return json(route, { ...record, company_name: 'New Buyer' })
  }
  await open(page)
  const dialog = await create(page)
  await dialog.getByLabel('ARR amount').fill('9999999999999999.99')
  await expect(dialog.getByLabel('Currency code')).toHaveValue('')
  await dialog.getByLabel('Currency code').fill('XTS')
  await dialog.getByLabel('Stage', { exact: true }).selectOption('negotiation')
  await dialog.getByLabel('Expected close date').fill('2027-01-31')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect.poll(() => writes().length).toBe(1)
  expect(writes()[0].body).toMatchObject({
    deal_value_arr: '9999999999999999.99',
    currency: 'XTS',
    stage: 'negotiation',
    expected_close_date: '2027-01-31',
  })
  await expect(page.getByText('Deal saved.', { exact: true })).toHaveCount(0)
  await expect(dialog.getByRole('button', { name: 'Save deal' })).toBeDisabled()
  pending.release()
  await expect(dialog).toHaveCount(0)
  await expect(companyHeader(page, 'Server Buyer')).toBeVisible()
  await expect(page.getByText('Deal saved.', { exact: true })).toBeVisible()
})
test('legacy unknown currency is displayed honestly and unrelated edits do not invent money', async ({
  page,
}) => {
  const { state, writes } = await setup(page)
  state.rows = [{ ...record, currency: null }]
  state.mutation = async (route) => {
    state.rows = [{ ...record, currency: null, company_name: 'Renamed Buyer' }]
    return json(route, state.rows[0])
  }
  await open(page)
  await expect(page.getByText('Currency not recorded')).toBeVisible()
  await page.getByRole('button', { name: 'Edit Synthetic Buyer' }).click()
  await page.getByLabel('Company name').fill('Renamed Buyer')
  await page.getByRole('button', { name: 'Save deal' }).click()
  await expect(companyHeader(page, 'Renamed Buyer')).toBeVisible()
  expect(writes()[0]).toMatchObject({
    path: '/api/deals/41',
    method: 'PATCH',
    body: { company_name: 'Renamed Buyer' },
  })
})
test('invalid money and missing currency retain the draft without a write', async ({
  page,
}) => {
  const { writes } = await setup(page)
  await open(page)
  const dialog = await create(page)
  await dialog.getByLabel('ARR amount').fill('1.001')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(dialog.getByText(/Use a non-negative decimal/)).toBeVisible()
  await dialog.getByLabel('ARR amount').fill('100.01')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(
    dialog.getByText('Enter a currency code for this amount.')
  ).toBeVisible()
  await expect(dialog.getByLabel('ARR amount')).toHaveValue('100.01')
  expect(writes()).toHaveLength(0)
})
for (const status of [403, 404, 409, 422, 500]) {
  test(`mutation ${status} keeps input and reports no success`, async ({
    page,
  }) => {
    const { state } = await setup(page)
    state.mutation = (route) =>
      json(route, { detail: 'Synthetic rejection' }, status)
    await open(page)
    const dialog = await create(page)
    await dialog.getByRole('button', { name: 'Save deal' }).click()
    await expect(dialog.getByRole('alert')).toContainText(
      status === 403 ? 'This account cannot complete' : 'Synthetic rejection'
    )
    await expect(dialog.getByLabel('Company name')).toHaveValue('New Buyer')
    await expect(page.getByText('Deal saved.', { exact: true })).toHaveCount(0)
  })
}
test('uncertain retries preserve the operation key, guard synchronous double submits and change key with payload', async ({
  page,
}) => {
  const { state, writes } = await setup(page),
    pending = gate()
  state.mutation = async (route) => {
    await pending.wait
    return route.abort('failed')
  }
  await open(page)
  const dialog = await create(page)
  await dialog.locator('form').evaluate((form) => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
  await expect.poll(() => writes().length).toBe(1)
  pending.release()
  await expect(dialog.getByRole('alert')).toContainText(
    'could not confirm whether'
  )
  state.mutation = (route) => json(route, { detail: 'Still processing' }, 409)
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(dialog.getByRole('alert')).toContainText('Still processing')
  expect(writes()[1].key).toBe(writes()[0].key)
  expect(writes()[0].key).toBeTruthy()
  await dialog.getByLabel('Company name').fill('Different Buyer')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect.poll(() => writes().length).toBe(3)
  expect(writes()[2].key).not.toBe(writes()[0].key)
})
test('acknowledged save and failed reload have distinct messages', async ({
  page,
}) => {
  const { state } = await setup(page)
  state.mutation = (route) => {
    state.readStatus = 500
    return json(route, record)
  }
  await open(page)
  const dialog = await create(page)
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(
    page.getByText(
      'Deal saved, but the list could not be refreshed. Try again to load it.'
    )
  ).toBeVisible()
  await expect(page.locator('[data-state="error"]')).toBeVisible()
  state.readStatus = 200
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(companyHeader(page, 'Synthetic Buyer')).toBeVisible()
})
test('discard warning preserves a draft on cancel and clears it only after confirmation', async ({
  page,
}) => {
  await setup(page)
  await open(page)
  const dialog = await create(page)
  await page.keyboard.press('Escape')
  const warning = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await expect(warning).toBeVisible()
  await warning.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog.getByLabel('Company name')).toHaveValue('New Buyer')
  await page.keyboard.press('Escape')
  await warning.getByRole('button', { name: 'Discard changes' }).click()
  await expect(dialog).toHaveCount(0)
  await page.getByRole('button', { name: 'Create deal', exact: true }).click()
  await expect(page.getByLabel('Company name')).toHaveValue('')
})
test('late previous-workspace list cannot replace current results', async ({
  page,
}) => {
  const { state, calls } = await setup(page),
    pending = gate()
  state.readWait = pending.wait
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await expect
    .poll(() => calls.filter((call) => call.path === '/api/deals').length)
    .toBeGreaterThan(0)
  state.readWait = Promise.resolve()
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect(companyHeader(page, 'Current Buyer')).toBeVisible()
  pending.release()
  await expect(companyHeader(page, 'Synthetic Buyer')).toHaveCount(0)
})
test('workspace change already in flight discards a late old-workspace save acknowledgment', async ({
  page,
}) => {
  const { state, writes, calls } = await setup(page),
    switching = gate(),
    saving = gate()
  state.switchWait = switching.wait
  state.mutation = async (route) => {
    await saving.wait
    return json(route, record).catch(() => {})
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await open(page)
  await expect(companyHeader(page, 'Synthetic Buyer')).toBeVisible()
  await page
    .getByRole('combobox', { name: 'Workspace', exact: true })
    .selectOption('8')
  await expect
    .poll(
      () =>
        calls.filter((call) => call.path === '/api/auth/switch-workspace')
          .length
    )
    .toBe(1)
  const dialog = await create(page)
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect.poll(() => writes().length).toBe(1)
  switching.release()
  await expect(companyHeader(page, 'Current Buyer')).toBeVisible()
  saving.release()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByText('Deal saved.', { exact: true })).toHaveCount(0)
})
for (const width of [360, 768, 1440]) {
  test(`long content, keyboard focus and accessibility at ${width}px`, async ({
    page,
  }, testInfo) => {
    const { state } = await setup(page)
    state.rows = [
      {
        ...record,
        company_name: 'LongCompany'.repeat(20),
        buyer_contact_email: `${'long'.repeat(20)}@example.com`,
      },
    ]
    await page.setViewportSize({ width, height: 900 })
    await open(page)
    await expect(page.getByRole('region', { name: 'Deals list' })).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    const evidenceDir = path.resolve('../../artifacts/acceptance/TC-15-049a')
    mkdirSync(path.join(evidenceDir, 'screenshots'), { recursive: true })
    for (const surface of ['list', 'dialog'] as const) {
      if (surface === 'dialog') {
        await page
          .getByRole('button', { name: 'Create deal', exact: true })
          .focus()
        await page.keyboard.press('Enter')
        const dialog = page.getByRole('dialog', {
          name: 'Create deal',
          exact: true,
        })
        await expect(dialog).toBeVisible()
        for (let index = 0; index < 14; index++) {
          await page.keyboard.press('Tab')
          expect(
            await dialog.evaluate((node) =>
              node.contains(document.activeElement)
            )
          ).toBe(true)
        }
      }
      const axe = await new AxeBuilder({ page }).analyze()
      const violations = axe.violations.map((item) => ({
        id: item.id,
        impact: item.impact,
        nodes: item.nodes.length,
      }))
      const report = path.join(evidenceDir, `axe-${surface}-${width}.json`)
      writeFileSync(
        report,
        JSON.stringify(
          { width, violationCount: violations.length, violations },
          null,
          2
        )
      )
      await testInfo.attach(`axe-${surface}-${width}`, {
        path: report,
        contentType: 'application/json',
      })
      expect(violations).toEqual([])
      const screenshot = path.join(
        evidenceDir,
        'screenshots',
        `deals-${surface}-${width}.png`
      )
      await page.screenshot({ path: screenshot, fullPage: true })
      await testInfo.attach(`deals-${surface}-${width}`, {
        path: screenshot,
        contentType: 'image/png',
      })
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth
        )
      ).toBe(true)
    }
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create deal', exact: true })
    ).toBeFocused()
  })
}

for (const [name, body] of [
  ['malformed', {}],
  ['foreign workspace', { ...record, workspace_id: 8 }],
] as const) {
  test(`does not acknowledge a ${name} save response`, async ({ page }) => {
    const { state } = await setup(page)
    state.mutation = (route) => json(route, body)
    await open(page)
    const dialog = await create(page)
    await dialog.getByRole('button', { name: 'Save deal' }).click()
    await expect(dialog.getByRole('alert')).toContainText(
      'could not confirm whether'
    )
    await expect(dialog.getByLabel('Company name')).toHaveValue('New Buyer')
    await expect(page.getByText('Deal saved.', { exact: true })).toHaveCount(0)
  })
}
test('cannot silently clear a stored amount or date with an unsupported patch', async ({
  page,
}) => {
  const { writes } = await setup(page)
  await open(page)
  await page.getByRole('button', { name: 'Edit Synthetic Buyer' }).click()
  const dialog = page.getByRole('dialog', { name: 'Edit deal' })
  await dialog.getByLabel('ARR amount').fill('')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(
    dialog.getByText(
      'This saved value cannot be cleared here. Enter a replacement.'
    )
  ).toBeVisible()
  await dialog.getByLabel('ARR amount').fill(record.deal_value_arr)
  await dialog.getByLabel('Expected close date').fill('')
  await dialog.getByRole('button', { name: 'Save deal' }).click()
  await expect(
    dialog.getByText(
      'This saved value cannot be cleared here. Enter a replacement.'
    )
  ).toBeVisible()
  expect(writes()).toHaveLength(0)
})
