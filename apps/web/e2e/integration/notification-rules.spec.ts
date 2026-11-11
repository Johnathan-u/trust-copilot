import { expect, test, type BrowserContext, type Page } from '@playwright/test'

type Fixture = {
  adminEmail: string
  editorEmail: string
  password: string
  memberUserId: number
  memberName: string
  adminName: string
  suspendedName: string
  logRecipient: string
  logId: number
}

function fixture(): Fixture {
  const serialized = process.env.TC_RULES_FIXTURE
  if (!serialized) {
    throw new Error(
      'Run this spec through the PostgreSQL rules acceptance test'
    )
  }
  return JSON.parse(serialized) as Fixture
}

async function localRequestsOnly(context: BrowserContext, baseURL: string) {
  const external: string[] = []
  await context.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.origin === new URL(baseURL).origin) return route.continue()
    external.push(url.origin)
    return route.abort('blockedbyclient')
  })
  return external
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  const emailInput = page.locator('input[type="email"]')
  const passwordInput = page.locator('input[type="password"]')
  await expect(emailInput).toBeVisible()
  await emailInput.pressSequentially(email, { delay: 1 })
  await passwordInput.pressSequentially(password, { delay: 1 })
  const response = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === '/api/auth/login' &&
      res.request().method() === 'POST'
  )
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  expect((await response).status()).toBe(200)
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function openRules(page: Page) {
  await page.goto('/dashboard/notifications')
  await expect(
    page.getByRole('heading', { name: 'Alerts / Notifications' })
  ).toBeVisible()
}

async function readPolicies(page: Page) {
  const response = await page.request.get('/api/notifications/policies')
  expect(response.status()).toBe(200)
  return response.json()
}

async function readLog(page: Page) {
  const response = await page.request.get(
    '/api/notifications/log?page=1&page_size=25'
  )
  expect(response.status()).toBe(200)
  return response.json()
}

async function setRuleEnabled(page: Page, enabled: boolean) {
  const response = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return (
      /^\/api\/notifications\/policies\/\d+$/.test(url.pathname) &&
      res.request().method() === 'PATCH'
    )
  })
  await page
    .getByRole('button', { name: enabled ? 'Enable' : 'Disable', exact: true })
    .click()
  const result = await response
  expect(result.status()).toBe(200)
  expect(await result.json()).toMatchObject({ enabled })
  await expect(
    page.getByRole('button', {
      name: enabled ? 'Disable' : 'Enable',
      exact: true,
    })
  ).toBeVisible()
}

test('before restart: an admin creates, disables and re-enables a rule', async ({
  page,
  baseURL,
}) => {
  const data = fixture()
  const external = await localRequestsOnly(page.context(), baseURL!)
  await login(page, data.adminEmail, data.password)
  await openRules(page)
  await expect(page.getByText(data.logRecipient)).toBeVisible()
  await expect(page.getByText('dead lettered', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Add rule', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Add Alert Rule' })
  ).toBeVisible()
  await expect(page.getByText('User email or ID')).toHaveCount(0)
  await expect(page.getByPlaceholder('e.g. user@company.com')).toHaveCount(0)
  await page.getByLabel('Event').selectOption({ label: 'Member joined' })
  await page.getByLabel('Recipients').selectOption('user')
  const member = page.getByLabel('Workspace member')
  await expect(member.locator('option')).toHaveText([
    'Select a member',
    data.adminName,
    data.memberName,
  ])
  await expect(
    member.locator('option', { hasText: data.suspendedName })
  ).toHaveCount(0)
  await member.selectOption({ label: data.memberName })
  const created = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === '/api/notifications/policies' &&
      res.request().method() === 'POST'
  )
  await page.getByRole('button', { name: 'Add Rule', exact: true }).click()
  const createResponse = await created
  expect(createResponse.status()).toBe(200)
  expect(createResponse.request().postDataJSON()).toEqual({
    event_type: 'member.joined',
    recipient_type: 'user',
    recipient_value: String(data.memberUserId),
  })
  await expect(page.getByText(`user: ${data.memberUserId}`)).toBeVisible()

  await setRuleEnabled(page, false)
  let policies = await readPolicies(page)
  expect(policies.policies).toEqual([
    expect.objectContaining({
      event_type: 'member.joined',
      enabled: false,
      recipient_type: 'user',
      recipient_value: String(data.memberUserId),
    }),
  ])
  await setRuleEnabled(page, true)
  policies = await readPolicies(page)
  expect(policies.policies).toEqual([
    expect.objectContaining({
      event_type: 'member.joined',
      enabled: true,
      recipient_type: 'user',
      recipient_value: String(data.memberUserId),
    }),
  ])
  const log = await readLog(page)
  expect(log.total).toBe(1)
  expect(log.entries).toEqual([
    expect.objectContaining({
      id: data.logId,
      event_type: 'member.joined',
      channel: 'email',
      recipient_email: data.logRecipient,
      status: 'failed',
      delivery_state: 'dead-lettered',
      delivered_to_provider: false,
      provider_mode: 'fixture',
    }),
  ])
  await expect(page.getByText(data.logRecipient)).toBeVisible()
  expect(external).toEqual([])
})

test('after restart: the rule and delivery log still agree and a non-admin has no admin controls', async ({
  page,
  browser,
  baseURL,
}) => {
  const data = fixture()
  const external = await localRequestsOnly(page.context(), baseURL!)
  await login(page, data.adminEmail, data.password)
  await openRules(page)
  await expect(page.getByText(`user: ${data.memberUserId}`)).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Disable', exact: true })
  ).toBeVisible()
  await expect(page.getByText(data.logRecipient)).toBeVisible()
  await expect(page.getByText('dead lettered', { exact: true })).toBeVisible()
  const policies = await readPolicies(page)
  expect(policies.policies).toEqual([
    expect.objectContaining({
      enabled: true,
      recipient_type: 'user',
      recipient_value: String(data.memberUserId),
    }),
  ])
  const log = await readLog(page)
  expect(log.entries[0]).toMatchObject({
    id: data.logId,
    recipient_email: data.logRecipient,
    delivered_to_provider: false,
  })

  const editor = await browser.newContext({ baseURL })
  try {
    const editorExternal = await localRequestsOnly(editor, baseURL!)
    const editorPage = await editor.newPage()
    await login(editorPage, data.editorEmail, data.password)
    await openRules(editorPage)
    await expect(
      editorPage.getByText(
        'Admin access is required to manage workspace alert rules.'
      )
    ).toBeVisible()
    await expect(
      editorPage.getByRole('checkbox', { name: 'Email' })
    ).toBeVisible()
    for (const name of [
      'Add rule',
      'Add Rule',
      'Disable',
      'Enable',
      'Remove',
    ]) {
      await expect(
        editorPage.getByRole('button', { name, exact: true })
      ).toHaveCount(0)
    }
    for (const name of [
      'Alert Rules',
      'Recent Activity',
      'Delivery attempts',
    ]) {
      await expect(
        editorPage.getByRole('heading', { name, exact: true })
      ).toHaveCount(0)
    }
    await expect(editorPage.getByText(data.logRecipient)).toHaveCount(0)
    await expect(
      editorPage.getByText(`user: ${data.memberUserId}`)
    ).toHaveCount(0)
    expect(
      (await editorPage.request.get('/api/notifications/policies')).status()
    ).toBe(403)
    expect(
      (await editorPage.request.get('/api/notifications/log')).status()
    ).toBe(403)
    expect(editorExternal).toEqual([])
  } finally {
    await editor.close()
  }
  expect(external).toEqual([])
})
