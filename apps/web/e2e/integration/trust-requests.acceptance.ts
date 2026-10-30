import { expect, test, type BrowserContext, type Page } from '@playwright/test'

type Reply = {
  id: number
  body: string
  body_revision: number
  approved_revision: number | null
  approved_by: number | null
  approved_at: string | null
  delivery_status: string | null
  delivery_attempts: number | null
  delivery_started_at: string | null
  delivery_accepted_at: string | null
  delivery_error: string | null
}
type Fixture = {
  workspaceId: number
  password: string
  internalId: number
  missingId: number
  reviewer: { id: number; email: string; memberId: number }
  admin: { id: number; email: string; memberId: number }
  main: { id: number; subject: string }
  attachment: { id: number; subject: string }
  foreign: { id: number; subject: string }
  persisted?: Reply[]
}
function fixture(): Fixture {
  const raw = process.env.TC_TRUST_FIXTURE
  if (!raw)
    throw new Error('Run through the PostgreSQL incoming Trust acceptance test')
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
async function openRequest(page: Page, request: Fixture['main']) {
  await page.goto('/dashboard/trust-requests')
  await page.getByRole('button', { name: new RegExp(request.subject) }).click()
  await expect(
    page.getByRole('heading', { name: request.subject, exact: true })
  ).toBeVisible()
}
function replyArticle(page: Page, id: number) {
  return page.getByRole('article', { name: `Reply ${id}`, exact: true })
}
async function responseTo(
  page: Page,
  path: string,
  method: string,
  action: () => Promise<void>
) {
  const response = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === path && res.request().method() === method
  )
  await action()
  return response
}
async function createDraft(page: Page, requestId: number, body: string) {
  await page.getByLabel('Reply text', { exact: true }).fill(body)
  const saved = await responseTo(
    page,
    `/api/trust-requests/${requestId}/replies`,
    'POST',
    () => page.getByRole('button', { name: 'Save draft', exact: true }).click()
  )
  expect(saved.status()).toBe(200)
  const draft = (await saved.json()) as Reply
  expect(draft.body).toBe(body)
  expect(draft.body_revision).toBe(1)
  expect(draft.approved_revision).toBeNull()
  expect(draft.delivery_status).toBe('draft')
  return draft
}
async function createApproved(page: Page, requestId: number, body: string) {
  const draft = await createDraft(page, requestId, body)
  const article = replyArticle(page, draft.id)
  await article.getByLabel(/I reviewed saved revision 1/).check()
  const approved = await responseTo(
    page,
    `/api/trust-requests/${requestId}/replies/${draft.id}/approve`,
    'POST',
    () => article.getByRole('button', { name: 'Approve revision' }).click()
  )
  expect(approved.status()).toBe(200)
  await expect(
    article.getByRole('button', { name: 'Send approved reply' })
  ).toBeEnabled()
  return (await approved.json()) as Reply
}
async function savedReplies(page: Page, requestId: number) {
  const response = await page.request.get(
    `/api/trust-requests/${requestId}/notes`
  )
  expect(response.status()).toBe(200)
  return (await response.json()) as Reply[]
}

test('before restart: real UI creates and approves persisted reply revisions', async ({
  page,
  baseURL,
}) => {
  const data = fixture()
  expect(await page.context().cookies()).toEqual([])
  const external = await localOnly(page.context(), baseURL!)
  await login(page, data.reviewer.email, data.password)
  await openRequest(page, data.main)
  await expect(
    page.getByRole('heading', { name: /Internal note/ })
  ).toBeVisible()
  await expect(
    page.getByText('Synthetic internal review note.', { exact: true })
  ).toBeVisible()
  const first = await createApproved(
    page,
    data.main.id,
    'Persisted approved reply.'
  )
  const second = await createApproved(
    page,
    data.main.id,
    'Approved unavailable delivery probe.'
  )
  const unapproved = await createDraft(
    page,
    data.main.id,
    'Persisted unapproved draft.'
  )
  const notes = await savedReplies(page, data.main.id)
  expect(notes).toHaveLength(4)
  for (const reply of [first, second]) {
    const saved = notes.find((note) => note.id === reply.id)!
    expect(saved).toMatchObject({
      body: reply.body,
      body_revision: 1,
      approved_revision: 1,
      approved_by: data.reviewer.id,
      approved_at: reply.approved_at,
      delivery_status: 'approved',
      delivery_attempts: 0,
      delivery_started_at: null,
      delivery_accepted_at: null,
    })
  }
  expect(notes.find((note) => note.id === unapproved.id)).toMatchObject({
    body: 'Persisted unapproved draft.',
    body_revision: 1,
    approved_revision: null,
    approved_by: null,
    approved_at: null,
    delivery_status: 'draft',
    delivery_attempts: 0,
  })
  await expect(
    page.getByRole('button', { name: new RegExp(data.foreign.subject) })
  ).toHaveCount(0)
  expect(external).toEqual([])
})

test('after restart: approval survives fresh login, real conflicts retain input and attachments fail closed', async ({
  page,
  browser,
  baseURL,
}, testInfo) => {
  const data = fixture()
  expect(data.persisted).toHaveLength(3)
  expect(await page.context().cookies()).toEqual([])
  const external = await localOnly(page.context(), baseURL!)
  await login(page, data.reviewer.email, data.password)
  await openRequest(page, data.main)
  const notes = await savedReplies(page, data.main.id)
  for (const saved of data.persisted!) {
    const restored = notes.find((note) => note.id === saved.id)!
    expect(restored).toMatchObject({
      body: saved.body,
      body_revision: saved.body_revision,
      approved_revision: saved.approved_revision,
      approved_by: saved.approved_by,
      approved_at: saved.approved_at,
      delivery_status: saved.delivery_status,
      delivery_attempts: 0,
    })
    await expect(page.getByLabel(`Reply ${saved.id} text`)).toHaveValue(
      saved.body
    )
  }
  const [original, delivery, unapproved] = data.persisted!
  await expect(
    replyArticle(page, unapproved.id).getByRole('button', {
      name: 'Send approved reply',
    })
  ).toHaveCount(0)
  const deliveryArticle = replyArticle(page, delivery.id)
  const sent = await responseTo(
    page,
    `/api/trust-requests/${data.main.id}/replies/${delivery.id}/send`,
    'POST',
    () =>
      deliveryArticle
        .getByRole('button', { name: 'Send approved reply' })
        .click()
  )
  expect(sent.status()).toBe(200)
  expect(await sent.json()).toMatchObject({
    delivery_status: 'unavailable',
    delivery_attempts: 0,
    delivery_started_at: null,
    delivery_accepted_at: null,
  })
  await expect(
    deliveryArticle.getByText(
      'Delivery unavailable — provider was not called',
      { exact: true }
    )
  ).toBeVisible()
  await expect(
    deliveryArticle.getByRole('button', { name: 'Send approved reply' })
  ).toBeDisabled()

  const edit = replyArticle(page, original.id)
  await edit
    .getByLabel(`Reply ${original.id} text`)
    .fill('Edited after restart.')
  await edit.getByLabel(/I reviewed saved revision 1/).check()
  const edited = await responseTo(
    page,
    `/api/trust-requests/${data.main.id}/replies/${original.id}`,
    'PATCH',
    () => edit.getByRole('button', { name: 'Save new revision' }).click()
  )
  expect(edited.status()).toBe(200)
  expect(await edited.json()).toMatchObject({
    body_revision: 2,
    approved_revision: null,
    approved_by: null,
    approved_at: null,
    delivery_status: 'draft',
  })
  const fresh = (await savedReplies(page, data.main.id)).find(
    (note) => note.id === original.id
  )!
  expect(fresh).toMatchObject({
    body: 'Edited after restart.',
    body_revision: 2,
    approved_revision: null,
    approved_by: null,
    approved_at: null,
    delivery_status: 'draft',
  })

  const admin = await browser.newContext({
    baseURL,
    extraHTTPHeaders: {
      Origin: baseURL!,
      Referer: `${baseURL}/dashboard/trust-requests`,
    },
  })
  try {
    const adminExternal = await localOnly(admin, baseURL!)
    const adminPage = await admin.newPage()
    await login(adminPage, data.admin.email, data.password)
    await edit
      .getByLabel(`Reply ${original.id} text`)
      .fill('My unsaved stale revision.')
    await edit.getByLabel(/I reviewed saved revision 2/).check()
    const concurrent = await admin.request.patch(
      `/api/trust-requests/${data.main.id}/replies/${original.id}`,
      { data: { revision: 2, body: 'Concurrent saved revision.' } }
    )
    expect(concurrent.status()).toBe(200)
    expect(await concurrent.json()).toMatchObject({
      body_revision: 3,
      approved_revision: null,
    })
    const stale = await responseTo(
      page,
      `/api/trust-requests/${data.main.id}/replies/${original.id}`,
      'PATCH',
      () => edit.getByRole('button', { name: 'Save new revision' }).click()
    )
    expect(stale.status()).toBe(409)
    await expect(edit.getByRole('alert')).toContainText('Reload saved replies')
    await expect(edit.getByLabel(`Reply ${original.id} text`)).toHaveValue(
      'My unsaved stale revision.'
    )
    await expect(
      edit.getByRole('button', { name: 'Save new revision' })
    ).toBeDisabled()
    await page.getByRole('button', { name: 'Reload saved replies' }).click()
    await expect(
      edit.getByText('Concurrent saved revision.', { exact: true })
    ).toBeVisible()
    await expect(edit.getByLabel(`Reply ${original.id} text`)).toHaveValue(
      'My unsaved stale revision.'
    )
    await expect(
      edit.getByRole('button', { name: 'Save new revision' })
    ).toBeDisabled()
    const protectedBefore = await savedReplies(adminPage, data.main.id)

    // Foreign and absent requests have the same real authorized 404. The
    // foreign row has a storage key; an accidental read is caught by the socket guard.
    const foreign = await admin.request.get(
      `/api/trust-requests/${data.foreign.id}/attachment`
    )
    const missing = await admin.request.get(
      `/api/trust-requests/${data.missingId}/attachment`
    )
    expect(foreign.status()).toBe(404)
    expect(missing.status()).toBe(404)
    expect(await foreign.json()).toEqual({ detail: 'Trust request not found' })
    expect(await missing.json()).toEqual({ detail: 'Trust request not found' })
    page.once('dialog', (dialog) => dialog.accept())
    await page
      .getByRole('button', { name: new RegExp(data.attachment.subject) })
      .click()
    await page
      .getByLabel('Reply text', { exact: true })
      .fill('Local text retained after denied attachment.')
    const absentAttachment = await responseTo(
      page,
      `/api/trust-requests/${data.attachment.id}/attachment`,
      'GET',
      () => page.getByRole('button', { name: 'Download attachment' }).click()
    )
    expect(absentAttachment.status()).toBe(404)
    expect(await absentAttachment.json()).toEqual({
      detail: 'No attachment on this trust request',
    })
    await expect(
      page.getByRole('region', { name: 'Request detail' }).getByRole('alert')
    ).toContainText('unavailable')
    await expect(page.getByLabel('Reply text', { exact: true })).toHaveValue(
      'Local text retained after denied attachment.'
    )
    const suspension = await admin.request.patch(
      `/api/members/${data.reviewer.memberId}/suspend`,
      { data: { suspended: true } }
    )
    expect(suspension.status()).toBe(200)
    const denied = await responseTo(
      page,
      `/api/trust-requests/${data.attachment.id}/attachment`,
      'GET',
      () => page.getByRole('button', { name: 'Download attachment' }).click()
    )
    expect(denied.status()).toBe(403)
    await expect(
      page.getByRole('region', { name: 'Request detail' }).getByRole('alert')
    ).toContainText('permission')
    await expect(page.getByLabel('Reply text', { exact: true })).toHaveValue(
      'Local text retained after denied attachment.'
    )
    expect(await savedReplies(adminPage, data.main.id)).toEqual(protectedBefore)
    expect(adminExternal).toEqual([])
  } finally {
    await admin.close()
  }
  expect(external).toEqual([])
  await testInfo.attach('incoming-real-api-assertions', {
    body: JSON.stringify({
      fresh_login: true,
      persisted_approval: true,
      edit_invalidated_approval: true,
      stale_status: 409,
      stale_text_retained: true,
      unavailable_attempts: 0,
      attachment_statuses: [404, 404, 404, 403],
    }),
    contentType: 'application/json',
  })
})
