import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

// Deterministic browser control paths. Real Slack, Gmail, and SMTP stay out of this spec.
test.use({ storageState: { cookies: [], origins: [] } })
test.setTimeout(60_000)

const marker = 'sk_live_notshown'
const SOURCE = 'source quote: private evidence'

type Role = 'admin' | 'editor'
type AttemptsMode =
  'ready' | 'empty' | 'error' | 'forbidden' | 'malformed' | 'hold'

function attempt(overrides: Record<string, unknown> = {}) {
  return {
    id: 9,
    event_type: 'member.joined',
    channel: 'email',
    recipient: 'ada@example.com',
    user_id: 4,
    state: 'dead-lettered',
    attempt_number: 3,
    max_attempts: 3,
    dedupe_key: 'a'.repeat(64),
    delivered_to_provider: false,
    provider_mode: 'fixture',
    template_key: 'member.joined:email',
    destination: 'ada@example.com',
    rendered_subject: `Member joined — ${SOURCE}`,
    rendered_body: `${SOURCE} ${marker}`,
    error_code: 'unknown',
    error: marker,
    in_app_notification_id: null,
    is_read: null,
    created_at: '2026-11-11T22:29:00.123456',
    ...overrides,
  }
}

const readyAttempts = {
  schema_version: 1,
  total: 6,
  page: 1,
  attempts: [
    attempt({ id: 11, state: 'retrying', attempt_number: 1 }),
    attempt({
      id: 10,
      state: 'deduped',
      attempt_number: 0,
      error_code: 'claimed',
    }),
    attempt({
      id: 9,
      channel: 'slack',
      state: 'suppressed-by-preference',
      attempt_number: 0,
      template_key: 'member.joined:slack',
      destination: 'C0123',
      error_code: null,
      provider_mode: null,
    }),
    attempt({ id: 6 }),
    attempt({
      id: 8,
      channel: 'in_app',
      state: 'sent',
      attempt_number: 1,
      max_attempts: 1,
      template_key: 'member.joined:in_app',
      destination: 'user:4',
      provider_mode: 'local',
      error_code: null,
      in_app_notification_id: 15,
      is_read: false,
    }),
    attempt({
      id: 7,
      channel: 'in_app',
      state: 'queued',
      attempt_number: 0,
      max_attempts: 1,
      template_key: 'member.joined:in_app',
      destination: 'user:4',
      provider_mode: 'local',
      error_code: null,
      in_app_notification_id: 16,
      is_read: true,
    }),
  ],
}
function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function me(role: Role) {
  const canAdmin = role === 'admin'
  return {
    id: 42,
    email: 'operator@example.com',
    display_name: 'Synthetic Operator',
    workspace_id: 7,
    workspace_name: 'Synthetic workspace',
    workspace_slug: 'synthetic',
    role,
    workspaces: [
      { id: 7, name: 'Synthetic workspace', slug: 'synthetic', role },
    ],
    permissions: {
      can_admin: canAdmin,
      can_edit: canAdmin || role === 'editor',
      can_review: true,
      can_export: canAdmin,
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
}

async function installApi(
  page: Page,
  options: {
    role?: Role
    attempts?: AttemptsMode
    preferenceStatus?: number
  } = {}
) {
  const state = {
    role: options.role ?? 'admin',
    attempts: options.attempts ?? 'ready',
    preferenceStatus: options.preferenceStatus ?? 200,
    channels: { email: true, slack: true, in_app: false },
    hold: Promise.resolve(),
    releaseHold: () => {},
    calls: [] as string[],
  }
  state.hold = new Promise<void>((resolve) => {
    state.releaseHold = resolve
  })
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
    state.calls.push(`${request.method()} ${url.pathname}`)
    const pathname = url.pathname
    if (pathname === '/api/auth/me') return json(route, me(state.role))
    if (pathname === '/api/auth/alerts') return json(route, { alerts: [] })
    if (pathname === '/api/in-app-notifications/unread-count')
      return json(route, { count: 0 })
    if (pathname === '/api/notifications/channel-preferences') {
      if (request.method() === 'PUT') {
        if (state.preferenceStatus !== 200) {
          return json(route, { detail: marker }, state.preferenceStatus)
        }
        const body = request.postDataJSON() as {
          channel: 'email' | 'slack' | 'in_app'
          enabled: boolean
        }
        state.channels[body.channel] = body.enabled
        return json(route, {
          schema_version: 1,
          id: 1,
          channel: body.channel,
          event_type: null,
          enabled: body.enabled,
        })
      }
      return json(route, {
        schema_version: 1,
        channels: ['email', 'slack', 'in_app'],
        effective: state.channels,
        preferences: [],
      })
    }
    if (pathname === '/api/notifications/delivery-attempts') {
      if (state.attempts === 'hold') await state.hold
      if (state.attempts === 'error')
        return json(route, { detail: marker }, 500)
      if (state.attempts === 'forbidden')
        return json(route, { detail: 'Insufficient permissions' }, 403)
      if (state.attempts === 'malformed')
        return json(route, {
          schema_version: 1,
          total: 0,
          page: 1,
          attempts: marker,
        })
      if (state.attempts === 'empty')
        return json(route, {
          schema_version: 1,
          total: 0,
          page: 1,
          attempts: [],
        })
      return json(route, readyAttempts)
    }
    if (pathname === '/api/notifications/event-types')
      return json(route, { event_types: ['member.joined'] })
    if (pathname === '/api/notifications/policies')
      return json(route, { policies: [] })
    if (pathname === '/api/notifications/log')
      return json(route, {
        total: 1,
        page: 1,
        entries: [
          {
            id: 3,
            event_type: 'member.joined',
            channel: 'email',
            recipient_email: 'ada@example.com',
            subject: marker,
            status: 'failed',
            error: SOURCE,
            delivery_state: 'dead-lettered',
            delivered_to_provider: false,
            provider_mode: 'dev-stub',
            dedupe_key: 'b'.repeat(64),
            attempt_count: 3,
            created_at: '2026-11-11T22:29:00',
          },
        ],
      })
    if (pathname === '/api/compliance-alerts/active')
      return json(route, { alerts: [] })
    if (pathname === '/api/slack/status' || pathname === '/api/gmail/status')
      return json(route, { provider_mode: 'disabled' })
    return json(route, {})
  })
  return state
}

async function openNotifications(page: Page) {
  await page.goto('/dashboard/notifications')
  await expect(
    page.getByRole('heading', { name: 'Alerts / Notifications' })
  ).toBeVisible()
}

function attemptsRegion(page: Page) {
  return page.getByRole('region', { name: 'Delivery attempts' })
}

test('admin sees log and delivery-attempt states without secret content', async ({
  page,
}) => {
  await installApi(page)
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(region.getByText('retrying', { exact: true })).toBeVisible()
  await expect(region.getByText('deduped', { exact: true })).toBeVisible()
  await expect(region.getByText('claimed', { exact: true })).toBeVisible()
  await expect(
    region.getByText('suppressed-by-preference', { exact: true })
  ).toBeVisible()
  await expect(region.getByText('dead-lettered', { exact: true })).toBeVisible()
  await expect(region.getByText('member.joined:slack')).toBeVisible()
  await expect(region.getByText('Destination C0123')).toBeVisible()
  await expect(
    region.getByText('Destination ada@example.com').first()
  ).toBeVisible()
  await expect(region.getByText('Attempts 3')).toBeVisible()
  await expect(region.getByText('Attempts 0').first()).toBeVisible()
  await expect(region.getByText('No in-app message').first()).toBeVisible()
  await expect(region.getByText('Unread', { exact: true })).toBeVisible()
  await expect(region.getByText('Read', { exact: true })).toBeVisible()
  await expect(page.getByText('dead lettered', { exact: true })).toBeVisible()
  await expect(page.getByText('Not delivered to the provider')).toBeVisible()
  await expect(page.locator('body')).not.toContainText(marker)
  await expect(page.locator('body')).not.toContainText(SOURCE)
  await expect(page.locator('body')).not.toContainText('rendered_body')
})

test('delivery attempts stay loading until the response arrives', async ({
  page,
}) => {
  const state = await installApi(page, { attempts: 'hold' })
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(region.locator('[data-state="loading"]')).toBeVisible()
  await expect(region.getByText('No delivery attempts yet.')).toHaveCount(0)
  await expect(region.getByText('dead-lettered')).toHaveCount(0)
  state.releaseHold()
  await expect(region.getByText('dead-lettered', { exact: true })).toBeVisible()
  await expect(region.locator('[data-state="loading"]')).toHaveCount(0)
})

test('delivery attempts show an empty state', async ({ page }) => {
  await installApi(page, { attempts: 'empty' })
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(region.getByText('No delivery attempts yet.')).toBeVisible()
  await expect(region.locator('[data-state="empty"]')).toBeVisible()
  await expect(region.getByText('dead-lettered')).toHaveCount(0)
})

test('a delivery-attempts error is not an empty list', async ({ page }) => {
  await installApi(page, { attempts: 'error' })
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(region.getByText('Something went wrong')).toBeVisible()
  await expect(region.getByText('No delivery attempts yet.')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(marker)
})

test('a delivery-attempts 403 is explicit and does not echo the body', async ({
  page,
}) => {
  await installApi(page, { attempts: 'forbidden' })
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(region.getByText('This section is not available')).toBeVisible()
  await expect(region.locator('[data-failure="forbidden"]')).toBeVisible()
  await expect(region.getByText('No delivery attempts yet.')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(
    'Insufficient permissions'
  )
})

test('a malformed delivery-attempts payload is an error, not rows', async ({
  page,
}) => {
  await installApi(page, { attempts: 'malformed' })
  await openNotifications(page)
  const region = attemptsRegion(page)
  await expect(
    region.getByText('The response could not be read. Try again.')
  ).toBeVisible()
  await expect(region.getByText('No delivery attempts yet.')).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText(marker)
})

test('channel preference save survives a reload', async ({ page }) => {
  await installApi(page)
  await openNotifications(page)
  const inApp = page.getByRole('checkbox', { name: 'In-app' })
  await expect(inApp).not.toBeChecked()
  await inApp.click()
  await expect(page.getByText('Channel preference saved.')).toBeVisible()
  await expect(inApp).toBeChecked()
  await page.reload()
  await expect(page.getByRole('checkbox', { name: 'In-app' })).toBeChecked()
  await expect(
    page.getByText('Could not save that channel preference.')
  ).toHaveCount(0)
})

test('a failed channel save does not show success', async ({ page }) => {
  const state = await installApi(page, { preferenceStatus: 500 })
  await openNotifications(page)
  const inApp = page.getByRole('checkbox', { name: 'In-app' })
  await expect(inApp).not.toBeChecked()
  await inApp.click()
  await expect(
    page.getByText('Could not save that channel preference.')
  ).toBeVisible()
  await expect(inApp).not.toBeChecked()
  await expect(page.getByText('Channel preference saved.')).toHaveCount(0)
  expect(
    state.calls.filter((call) =>
      call.startsWith('PUT /api/notifications/channel-preferences')
    )
  ).toHaveLength(1)
})

test('a non-admin sees channels and does not request delivery attempts', async ({
  page,
}) => {
  const state = await installApi(page, { role: 'editor' })
  await openNotifications(page)
  await expect(
    page.getByText('Admin access is required to manage workspace alert rules.')
  ).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Email' })).toBeVisible()
  await expect(
    page.getByRole('region', { name: 'Delivery attempts' })
  ).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Alert Rules', exact: true })
  ).toHaveCount(0)
  await expect
    .poll(
      () =>
        state.calls.filter((call) => call.includes('channel-preferences'))
          .length
    )
    .toBeGreaterThan(0)
  expect(state.calls.some((call) => call.includes('delivery-attempts'))).toBe(
    false
  )
})

for (const width of [360, 768, 1440]) {
  test(`notifications keyboard and axe at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await installApi(page)
    await openNotifications(page)
    const region = attemptsRegion(page)
    await expect(
      region.getByText('dead-lettered', { exact: true })
    ).toBeVisible()
    const email = page.getByRole('checkbox', { name: 'Email' })
    const slack = page.getByRole('checkbox', { name: 'Slack' })
    await email.focus()
    await expect(email).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(slack).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.getByText('Channel preference saved.')).toBeVisible()
    await expect(slack).not.toBeChecked()
    await expect(slack).toBeFocused()
    const main = page.locator('#main-content')
    expect(
      await main.evaluate((node) => node.scrollWidth <= node.clientWidth)
    ).toBe(true)
    const result = await new AxeBuilder({ page })
      .include('#main-content')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const violations = result.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      nodes: item.nodes.length,
    }))
    const evidence = path.resolve('../../artifacts/acceptance/TC-19-008')
    mkdirSync(path.join(evidence, 'screenshots'), { recursive: true })
    const axePath = path.join(evidence, `axe-notifications-${width}.json`)
    writeFileSync(
      axePath,
      JSON.stringify(
        {
          width,
          surface: 'notifications',
          violationCount: violations.length,
          violations,
        },
        null,
        2
      )
    )
    const screenshot = path.join(
      evidence,
      'screenshots',
      `notifications-${width}.png`
    )
    await page.screenshot({ path: screenshot, fullPage: true })
    await testInfo.attach(`axe-notifications-${width}`, {
      path: axePath,
      contentType: 'application/json',
    })
    await testInfo.attach(`notifications-${width}`, {
      path: screenshot,
      contentType: 'image/png',
    })
    expect(violations).toEqual([])
  })
}
