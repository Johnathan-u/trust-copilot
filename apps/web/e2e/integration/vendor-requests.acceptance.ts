import { expect, test, type BrowserContext, type Page } from '@playwright/test'

type VendorRow = {
  id: number
  vendor_email: string
  status: string
  delivery_status: string
  submitted_at: string | null
  revoked_at: string | null
  link_token: string | null
  share_url?: string
}
type Fixture = {
  email: string
  password: string
  sendEmail: string
  resendEmail: string
  completeEmail: string
  finalResponse: string
}

const STATUS: Record<string, string> = {
  pending: 'Pending',
  in_progress: 'In Progress',
  expired: 'Expired',
  revoked: 'Revoked',
  completed: 'Completed',
}
const DELIVERY: Record<string, string> = {
  not_sent: 'Not sent',
  sending: 'Delivery awaiting confirmation',
  accepted: 'Accepted by email provider',
  uncertain: 'Delivery outcome unknown',
  unavailable: 'Email delivery unavailable',
  unknown: 'No recorded delivery outcome',
}

function fixture(): Fixture {
  const raw = process.env.TC_VENDOR_FIXTURE
  if (!raw)
    throw new Error('Run through the PostgreSQL vendor-request acceptance test')
  return JSON.parse(raw) as Fixture
}

async function localOnly(context: BrowserContext, baseURL: string) {
  const denied: string[] = []
  await context.route('**/*', async (route) => {
    const target = new URL(route.request().url())
    if (target.origin === new URL(baseURL).origin) return route.continue()
    denied.push(target.origin)
    return route.abort('blockedbyclient')
  })
  return denied
}

async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await expect(page.locator('input[type="email"]')).toBeVisible()
  await page
    .locator('input[type="email"]')
    .pressSequentially(email, { delay: 1 })
  await page
    .locator('input[type="password"]')
    .pressSequentially(password, { delay: 1 })
  const result = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === '/api/auth/login' &&
      res.request().method() === 'POST'
  )
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  expect((await result).status()).toBe(200)
  await expect(page).toHaveURL(/\/dashboard$/)
}

async function openRequests(page: Page) {
  await page.goto('/dashboard/requests')
  await expect(
    page.getByRole('heading', { name: 'Requests', exact: true })
  ).toBeVisible()
}

function rowFor(page: Page, email: string) {
  return page.getByRole('row').filter({
    has: page.getByText(email, { exact: true }),
  })
}

async function listed(page: Page) {
  const response = await page.request.get('/api/vendor-requests')
  expect(response.status()).toBe(200)
  const body = (await response.json()) as VendorRow[]
  expect(Array.isArray(body)).toBe(true)
  return body
}

async function expectUiMatchesApi(page: Page) {
  const rows = await listed(page)
  for (const row of rows) {
    const tr = rowFor(page, row.vendor_email)
    await expect(
      tr.getByText(STATUS[row.status], { exact: true })
    ).toBeVisible()
    await expect(
      tr.getByText(DELIVERY[row.delivery_status], { exact: true })
    ).toBeVisible()
  }
  return rows
}

async function createRequest(page: Page, email: string, message: string) {
  await page
    .getByRole('button', { name: 'Create Request', exact: true })
    .click()
  const dialog = page.getByRole('dialog', { name: 'Create Request' })
  await dialog.locator('input[type="email"]').fill(email)
  await dialog.locator('textarea').fill(message)
  const created = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return (
      url.pathname === '/api/vendor-requests' &&
      res.request().method() === 'POST'
    )
  })
  await dialog.getByRole('button', { name: 'Create Link', exact: true }).click()
  const response = await created
  expect(response.status()).toBe(200)
  const body = (await response.json()) as VendorRow
  expect(body.vendor_email).toBe(email)
  expect(body.status).toBe('pending')
  expect(body.delivery_status).toBe('not_sent')
  expect(body.submitted_at).toBeNull()
  expect(body.link_token).toBeTruthy()
  const result = page.getByRole('dialog', { name: 'Request Created' })
  await expect(result.locator('code')).toContainText(body.link_token!)
  await result.getByRole('button', { name: 'Done', exact: true }).click()
  await expect(result).toHaveCount(0)
  await expect(
    rowFor(page, email).getByText('Pending', { exact: true })
  ).toBeVisible()
  await expect(
    rowFor(page, email).getByText('Not sent', { exact: true })
  ).toBeVisible()
  return body
}

async function sendInvitation(page: Page, email: string) {
  const row = rowFor(page, email)
  const sent = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return url.pathname.endsWith('/send') && res.request().method() === 'POST'
  })
  await row
    .getByRole('button', { name: 'Send invitation', exact: true })
    .click()
  const response = await sent
  expect(response.status()).toBe(200)
  const body = (await response.json()) as VendorRow
  expect(body.delivery_status).toBe('unavailable')
  expect(body.status).not.toBe('completed')
  expect(body.link_token).toBeNull()
  expect(body.share_url).toBeUndefined()
  await expect(
    page.getByRole('dialog', { name: 'Invitation result' })
  ).toHaveCount(0)
  await expect(
    row.getByText('Email delivery unavailable', { exact: true })
  ).toBeVisible()
  await expect(row.getByText('Accepted by email provider')).toHaveCount(0)
  await expect(row.getByText(/\bdelivered\b/i)).toHaveCount(0)
  await expect(row.getByText('Completed', { exact: true })).toHaveCount(0)
}

async function revokeInvitation(page: Page, email: string) {
  const row = rowFor(page, email)
  await row.getByRole('button', { name: 'Revoke link', exact: true }).click()
  const dialog = page.getByRole('alertdialog', { name: 'Revoke vendor link?' })
  const revoked = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return url.pathname.endsWith('/revoke') && res.request().method() === 'POST'
  })
  await dialog.getByRole('button', { name: 'Revoke link', exact: true }).click()
  const response = await revoked
  expect(response.status()).toBe(200)
  const body = (await response.json()) as VendorRow
  expect(body.status).toBe('revoked')
  expect(body.submitted_at).toBeNull()
  await expect(row.getByText('Revoked', { exact: true })).toBeVisible()
  await expect(row.getByText('Completed', { exact: true })).toHaveCount(0)
  await expect(row.getByRole('button', { name: /invitation/i })).toHaveCount(0)
}

async function resendInvitation(page: Page, email: string) {
  const row = rowFor(page, email)
  await expect(
    row.getByText('Accepted by email provider', { exact: true })
  ).toBeVisible()
  const sent = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return url.pathname.endsWith('/resend') && res.request().method() === 'POST'
  })
  await row
    .getByRole('button', { name: 'Resend invitation', exact: true })
    .click()
  const response = await sent
  expect(response.status()).toBe(200)
  const body = (await response.json()) as VendorRow
  expect(body.delivery_status).toBe('unavailable')
  expect(body.status).not.toBe('completed')
  expect(body.link_token).toBeNull()
  await expect(
    page.getByRole('dialog', { name: 'Invitation result' })
  ).toHaveCount(0)
  await expect(
    row.getByText('Email delivery unavailable', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Accepted by email provider')).toHaveCount(0)
  await expect(page.getByText(/\bdelivered\b/i)).toHaveCount(0)
}

async function submitFinal(page: Page, token: string, responseText: string) {
  await page.goto(`/vendor-response?token=${encodeURIComponent(token)}`)
  await expect(
    page.getByRole('heading', { name: 'Vendor Request' })
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Request Completed' })
  ).toHaveCount(0)
  await page.getByLabel('Final response').fill(responseText)
  const submitted = page.waitForResponse((res) => {
    const url = new URL(res.url())
    return (
      url.pathname === '/api/vendor-response/submit' &&
      res.request().method() === 'POST'
    )
  })
  await page
    .getByRole('button', { name: 'Submit response', exact: true })
    .click()
  const response = await submitted
  expect(response.status()).toBe(200)
  const body = (await response.json()) as { status?: string }
  expect(body.status).toBe('completed')
  const posted = response.request().postDataJSON() as {
    token?: string
    response?: string
  }
  expect(posted.token).toBe(token)
  expect(posted.response).toBe(responseText)
  await expect(
    page.getByRole('heading', { name: 'Request Completed' })
  ).toBeVisible()
}

test('before restart: real UI creates, sends, revokes, resends, then completes only by submit', async ({
  page,
  baseURL,
}) => {
  const data = fixture()
  expect(await page.context().cookies()).toEqual([])
  const external = await localOnly(page.context(), baseURL!)
  await login(page, data.email, data.password)
  await openRequests(page)
  await expect(page.getByText(data.resendEmail, { exact: true })).toBeVisible()
  await expect(page.getByText('Completed', { exact: true })).toHaveCount(0)

  const sent = await createRequest(
    page,
    data.sendEmail,
    'Synthetic send and revoke request'
  )
  await sendInvitation(page, data.sendEmail)
  await revokeInvitation(page, data.sendEmail)
  await resendInvitation(page, data.resendEmail)
  await expect(page.getByText('Completed', { exact: true })).toHaveCount(0)

  const completing = await createRequest(
    page,
    data.completeEmail,
    'Synthetic completion request'
  )
  await expect(page.getByText('Completed', { exact: true })).toHaveCount(0)
  const beforeSubmit = await listed(page)
  expect(beforeSubmit.every((row) => row.status !== 'completed')).toBe(true)
  expect(beforeSubmit.every((row) => row.submitted_at === null)).toBe(true)

  await submitFinal(page, completing.link_token!, data.finalResponse)
  await openRequests(page)
  const rows = await expectUiMatchesApi(page)
  expect(
    rows
      .filter((row) => row.status === 'completed')
      .map((row) => row.vendor_email)
  ).toEqual([data.completeEmail])
  expect(rows.find((row) => row.vendor_email === data.sendEmail)).toMatchObject(
    {
      status: 'revoked',
      delivery_status: 'unavailable',
      submitted_at: null,
    }
  )
  expect(
    rows.find((row) => row.vendor_email === data.resendEmail)
  ).toMatchObject({
    status: 'pending',
    delivery_status: 'unavailable',
    submitted_at: null,
  })
  expect(rows.find((row) => row.id === sent.id)?.submitted_at).toBeNull()
  expect(external).toEqual([])
})

test('after restart: badges still match the saved rows and completion stays on the submission', async ({
  page,
  baseURL,
}) => {
  const data = fixture()
  expect(await page.context().cookies()).toEqual([])
  const external = await localOnly(page.context(), baseURL!)
  await login(page, data.email, data.password)
  await openRequests(page)
  const rows = await expectUiMatchesApi(page)
  expect(rows.map((row) => row.vendor_email).sort()).toEqual(
    [data.completeEmail, data.resendEmail, data.sendEmail].sort()
  )
  expect(rows.filter((row) => row.status === 'completed')).toEqual([
    expect.objectContaining({
      vendor_email: data.completeEmail,
      delivery_status: 'not_sent',
    }),
  ])
  const completed = rowFor(page, data.completeEmail)
  await expect(completed.getByText('Completed', { exact: true })).toBeVisible()
  await expect(
    completed.getByText('Response submitted', { exact: false })
  ).toBeVisible()
  await expect(completed.locator('select')).toHaveCount(0)
  const revoked = rowFor(page, data.sendEmail)
  await expect(revoked.getByText('Revoked', { exact: true })).toBeVisible()
  await expect(
    revoked.getByText('Email delivery unavailable', { exact: true })
  ).toBeVisible()
  await expect(revoked.getByText('Completed', { exact: true })).toHaveCount(0)
  const resent = rowFor(page, data.resendEmail)
  await expect(resent.getByText('Pending', { exact: true })).toBeVisible()
  await expect(
    resent.getByText('Email delivery unavailable', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Accepted by email provider')).toHaveCount(0)
  await expect(page.getByText(/\bdelivered\b/i)).toHaveCount(0)
  expect(external).toEqual([])
})
