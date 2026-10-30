import { expect, test, type Page, type Route } from '@playwright/test'

const syntheticMe = {
  id: 42,
  email: 'synthetic.reviewer@example.com',
  display_name: 'Synthetic Reviewer',
  workspace_id: 7,
  workspace_name: 'Synthetic Workspace',
  workspace_slug: 'synthetic',
  role: 'admin',
  workspaces: [
    { id: 7, name: 'Synthetic Workspace', slug: 'synthetic', role: 'admin' },
  ],
  permissions: {
    can_edit: true,
    can_review: true,
    can_admin: true,
    can_export: true,
  },
  needs_onboarding: false,
  subscription: { status: 'trialing', plan: 'synthetic' },
  mfa_enrolled: true,
  mfa_required_for_workspace: false,
  workspace_auth_policy: { mfa_required: false, session_max_age_seconds: null },
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function openInbox(page: Page, width = 1440) {
  const state = { count: 25, mutationStatus: 200, afterMutationCount: 24 }
  const rows = Array.from({ length: 20 }, (_, i) => ({
    id: i + 1,
    title: `Notification ${i + 1}`,
    body: 'Synthetic notification.',
    category: 'info',
    link: null,
    is_read: false,
    admin_only: false,
    created_at: null,
  }))
  await page.route('**/api/**', async (route) => {
    const { pathname } = new URL(route.request().url())
    if (pathname.endsWith('/api/auth/me')) return json(route, syntheticMe)
    if (pathname.endsWith('/api/auth/alerts'))
      return json(route, { alerts: [] })
    if (pathname.endsWith('/api/in-app-notifications/unread-count'))
      return json(route, { count: state.count })
    if (pathname.endsWith('/api/in-app-notifications'))
      return json(route, { total: 25, notifications: rows })
    if (
      pathname.includes('/api/in-app-notifications/') &&
      route.request().method() === 'POST'
    ) {
      if (state.mutationStatus !== 200)
        return json(route, { detail: 'Request rejected' }, state.mutationStatus)
      if (pathname.endsWith('/read-all'))
        rows.forEach((row) => {
          row.is_read = true
        })
      else {
        const id = Number(pathname.split('/').at(-2))
        const row = rows.find((item) => item.id === id)
        if (row) row.is_read = true
      }
      state.count = state.afterMutationCount
      return json(
        route,
        pathname.endsWith('/read-all') ? { updated: 25 } : { ok: true }
      )
    }
    if (pathname.endsWith('/api/dashboard/cards'))
      return json(route, { cards: [], has_custom: false })
    if (pathname.endsWith('/api/dashboard/cards/allowed-routes'))
      return json(route, {
        routes: ['/dashboard/documents'],
        icons: ['document'],
        sizes: ['medium'],
        visibility_scopes: ['all'],
      })
    return json(route, {})
  })
  // Route fixtures run in the browser; middleware needs its session cookie first.
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/dashboard$/)
  await expect(
    page.getByRole('heading', { name: 'Dashboard', exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'No shortcuts yet', exact: true })
  ).toBeVisible()
  const bell = page.getByRole('button', { name: 'Notifications', exact: true })
  await expect(bell).toContainText('25')
  const panelId = await bell.getAttribute('aria-controls')
  expect(panelId).toBeTruthy()
  const panel = page.locator(`[id="${panelId}"]`)
  await bell.click()
  await expect(panel).toBeVisible()
  await expect(page.getByText('Notification 20', { exact: true })).toBeVisible()
  await expect(page.getByText('25 unread', { exact: true })).toBeVisible()
  return { state, bell, panel }
}

for (const width of [360, 1440]) {
  test(`opening a 20-item page preserves the 25-item unread count at ${width}px`, async ({
    page,
  }) => {
    const { bell } = await openInbox(page, width)
    await expect(page.getByTitle('Unread', { exact: true })).toHaveCount(20)
    await expect(bell).toContainText('25')
  })
}

for (const mode of ['one', 'all']) {
  test(`rejected mark-${mode} keeps unread rows and the badge`, async ({
    page,
  }) => {
    const { state, bell, panel } = await openInbox(page)
    state.mutationStatus = mode === 'one' ? 403 : 500
    await (
      mode === 'one'
        ? page.getByText('Notification 1', { exact: true })
        : page.getByRole('button', { name: 'Mark all read' })
    ).click()
    const rejection = panel.getByRole('alert')
    await expect(rejection).toBeVisible()
    await expect(rejection).toHaveAttribute(
      'data-failure',
      mode === 'one' ? 'forbidden' : 'server'
    )
    await expect(page.getByTitle('Unread', { exact: true })).toHaveCount(20)
    await expect(page.getByText('25 unread', { exact: true })).toBeVisible()
    await expect(bell).toContainText('25')
  })
}

test('mark-one refreshes the total beyond the displayed page', async ({
  page,
}) => {
  const { bell } = await openInbox(page)
  await page.getByText('Notification 1', { exact: true }).click()
  await expect(page.getByText('24 unread', { exact: true })).toBeVisible()
  await expect(page.getByTitle('Unread', { exact: true })).toHaveCount(19)
  await expect(bell).toContainText('24')
})

test('mark-all uses the server count including newly arrived notifications', async ({
  page,
}) => {
  const { state, bell } = await openInbox(page)
  state.afterMutationCount = 3
  await page.getByRole('button', { name: 'Mark all read' }).click()
  await expect(page.getByText('3 unread', { exact: true })).toBeVisible()
  await expect(page.getByTitle('Unread', { exact: true })).toHaveCount(0)
  await expect(bell).toContainText('3')
})

test('reopening the list refreshes the authoritative unread count', async ({
  page,
}) => {
  const { state, bell } = await openInbox(page)
  await page.getByRole('button', { name: 'Close notifications' }).click()
  state.count = 42
  await bell.click()
  await expect(page.getByText('42 unread', { exact: true })).toBeVisible()
  await expect(bell).toContainText('42')
})
