import {
  expect,
  test,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from '@playwright/test'

type Item = { id: number; title: string }
type Fixture = {
  email: string
  reviewerEmail: string
  password: string
  visible: Item[]
  hidden: Item[]
  personal: Item
  shared: Item
  reviewerVisible: Item[]
}

function fixture(): Fixture {
  const serialized = process.env.TC_INBOX_FIXTURE
  if (!serialized) {
    throw new Error(
      'Run this spec through the PostgreSQL inbox acceptance test'
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
  // Match the existing real-login fixture's controlled-input interaction.
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

async function assertApi(
  request: APIRequestContext,
  visible: Item[],
  read: number[],
  count: number
) {
  const countResponse = await request.get(
    '/api/in-app-notifications/unread-count'
  )
  expect(countResponse.status()).toBe(200)
  expect(await countResponse.json()).toEqual({ count })
  const rows: unknown[] = []
  for (let offset = 0; offset < visible.length; offset += 20) {
    const response = await request.get(
      `/api/in-app-notifications?limit=20&offset=${offset}`
    )
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body).toEqual({
      total: visible.length,
      notifications: visible.slice(offset, offset + 20).map((item) => ({
        ...item,
        body: 'Synthetic content',
        category: 'info',
        link: null,
        is_read: read.includes(item.id),
        admin_only: false,
        created_at: '2026-01-01T00:00:00',
      })),
    })
    rows.push(...body.notifications)
  }
  return { count, rows }
}

async function assertInbox(
  page: Page,
  visible: Item[],
  read: number[],
  count: number,
  hidden: Item[] = []
) {
  const bell = page.getByRole('button', { name: 'Notifications', exact: true })
  const badge = bell.locator('span').filter({ hasText: /^\d+$/ })
  if (count) await expect(badge).toHaveText(String(count))
  else await expect(badge).toHaveCount(0)
  if ((await bell.getAttribute('aria-expanded')) !== 'true') await bell.click()
  const panelId = await bell.getAttribute('aria-controls')
  expect(panelId).toBeTruthy()
  const panel = page.locator(`[id="${panelId}"]`)
  await expect(panel).toBeVisible()
  await expect(
    panel.getByText(count ? `${count} unread` : 'All caught up', {
      exact: true,
    })
  ).toBeVisible()
  await expect(panel.locator('li')).toHaveCount(Math.min(20, visible.length))
  for (const item of visible.slice(0, 20)) {
    const row = panel.locator('li').filter({
      has: page.getByText(item.title, { exact: true }),
    })
    await expect(row).toHaveCount(1)
    await expect(row.getByTitle('Unread', { exact: true })).toHaveCount(
      read.includes(item.id) ? 0 : 1
    )
  }
  for (const item of hidden) {
    await expect(panel.getByText(item.title, { exact: true })).toHaveCount(0)
  }
  return panel
}

async function retryRead(request: APIRequestContext, id: number) {
  const response = await request.post(`/api/in-app-notifications/${id}/read`)
  expect(response.status()).toBe(200)
  expect(await response.json()).toEqual({ ok: true })
}

test('before restart: UI reads agree with real API pagination and visibility', async ({
  page,
  baseURL,
}, testInfo) => {
  const data = fixture()
  const external = await localRequestsOnly(page.context(), baseURL!)
  await login(page, data.email, data.password)
  await assertApi(page.request, data.visible, [], 25)
  const panel = await assertInbox(page, data.visible, [], 25, data.hidden)
  const read: number[] = []
  for (const item of [data.personal, data.shared]) {
    const response = page.waitForResponse(
      (res) =>
        new URL(res.url()).pathname ===
          `/api/in-app-notifications/${item.id}/read` &&
        res.request().method() === 'POST'
    )
    await panel.getByText(item.title, { exact: true }).click()
    const result = await response
    expect(result.status()).toBe(200)
    expect(await result.json()).toEqual({ ok: true })
    read.push(item.id)
    await assertInbox(page, data.visible, read, 25 - read.length, data.hidden)
    await retryRead(page.request, item.id)
  }
  for (const item of data.hidden) {
    const denied = await page.request.post(
      `/api/in-app-notifications/${item.id}/read`
    )
    expect(denied.status()).toBe(404)
    expect(await denied.json()).toEqual({ detail: 'Notification not found' })
  }
  const state = await assertApi(page.request, data.visible, read, 23)
  await assertInbox(page, data.visible, read, 23, data.hidden)
  expect(external).toEqual([])
  await testInfo.attach('api-ui-before-restart', {
    body: JSON.stringify(state),
    contentType: 'application/json',
  })
})

test('after restart: persisted reads, retries and other recipients still agree', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const data = fixture()
  const external = await localRequestsOnly(page.context(), baseURL!)
  await login(page, data.email, data.password)
  const read = [data.personal.id, data.shared.id]
  await assertApi(page.request, data.visible, read, 23)
  const panel = await assertInbox(page, data.visible, read, 23, data.hidden)
  await retryRead(page.request, data.shared.id)
  await retryRead(page.request, data.personal.id)
  await assertApi(page.request, data.visible, read, 23)
  const response = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === '/api/in-app-notifications/read-all' &&
      res.request().method() === 'POST'
  )
  await panel.getByRole('button', { name: 'Mark all read' }).click()
  const result = await response
  expect(result.status()).toBe(200)
  expect(await result.json()).toEqual({ updated: 23 })
  const allRead = data.visible.map((item) => item.id)
  await assertInbox(page, data.visible, allRead, 0, data.hidden)
  const retry = await page.request.post('/api/in-app-notifications/read-all')
  expect(retry.status()).toBe(200)
  expect(await retry.json()).toEqual({ updated: 0 })
  const state = await assertApi(page.request, data.visible, allRead, 0)
  await assertInbox(page, data.visible, allRead, 0, data.hidden)
  // A second actual user still sees both broadcasts unread. No shared legacy
  // flag or another user's receipt may be changed by the editor's read-all.
  const reviewer = await browser.newContext({ baseURL })
  try {
    const reviewerExternal = await localRequestsOnly(reviewer, baseURL!)
    const reviewerPage = await reviewer.newPage()
    await login(reviewerPage, data.reviewerEmail, data.password)
    await assertApi(reviewerPage.request, data.reviewerVisible, [], 3)
    await assertInbox(reviewerPage, data.reviewerVisible, [], 3)
    expect(reviewerExternal).toEqual([])
  } finally {
    await reviewer.close()
  }
  expect(external).toEqual([])
  await testInfo.attach('api-ui-after-restart', {
    body: JSON.stringify(state),
    contentType: 'application/json',
  })
})
