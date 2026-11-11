import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installApi(page: Page) {
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === '/api/auth/me') {
      return json(route, {
        id: 42,
        email: 'operator@example.com',
        display_name: 'Synthetic Operator',
        workspace_id: 7,
        workspace_name: 'Synthetic workspace',
        workspace_slug: 'synthetic',
        role: 'admin',
        workspaces: [
          {
            id: 7,
            name: 'Synthetic workspace',
            slug: 'synthetic',
            role: 'admin',
          },
        ],
        permissions: {
          can_admin: true,
          can_edit: true,
          can_review: true,
          can_export: true,
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
    }
    if (pathname === '/api/auth/alerts') return json(route, { alerts: [] })
    if (pathname === '/api/in-app-notifications/unread-count') {
      return json(route, { count: 0 })
    }
    if (pathname === '/api/notifications/channel-preferences') {
      return json(route, {
        schema_version: 1,
        channels: ['email', 'slack', 'in_app'],
        effective: { email: true, slack: true, in_app: false },
        preferences: [],
      })
    }
    if (pathname === '/api/notifications/delivery-attempts') {
      return json(route, { schema_version: 1, total: 0, page: 1, attempts: [] })
    }
    if (pathname === '/api/notifications/event-types') {
      return json(route, { event_types: ['member.joined'] })
    }
    if (pathname === '/api/notifications/policies')
      return json(route, { policies: [] })
    if (pathname === '/api/notifications/log') {
      return json(route, { total: 0, page: 1, entries: [] })
    }
    if (pathname === '/api/compliance-alerts/active')
      return json(route, { alerts: [] })
    if (pathname === '/api/slack/status' || pathname === '/api/gmail/status') {
      return json(route, { provider_mode: 'disabled' })
    }
    if (pathname === '/api/members') {
      return json(route, {
        members: [
          {
            id: 90,
            user_id: 17,
            email: 'ada.member@example.com',
            display_name: 'Ada Member',
            role: 'editor',
            suspended: false,
          },
          {
            id: 91,
            user_id: 18,
            email: 'paused.member@example.com',
            display_name: 'Paused Member',
            role: 'editor',
            suspended: true,
          },
        ],
      })
    }
    return json(route, {})
  })
}

for (const width of [360, 768, 1440]) {
  test(`rule recipient picker at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await installApi(page)
    await page.goto('/dashboard/notifications')
    await expect(
      page.getByRole('heading', { name: 'Alerts / Notifications' })
    ).toBeVisible()
    await page.getByRole('button', { name: 'Add rule', exact: true }).click()
    await page.getByLabel('Recipients').selectOption('user')
    const member = page.getByLabel('Workspace member')
    await expect(
      member.locator('option', { hasText: 'Ada Member' })
    ).toHaveCount(1)
    await expect(
      member.locator('option', { hasText: 'Paused Member' })
    ).toHaveCount(0)
    await expect(page.getByText('User email or ID')).toHaveCount(0)
    await expect(page.getByPlaceholder('e.g. user@company.com')).toHaveCount(0)
    await expect(
      page.getByText(
        "Choose an active workspace member. The rule stores that member's user id."
      )
    ).toBeVisible()
    await member.focus()
    await expect(member).toBeFocused()
    const main = page.locator('#main-content')
    expect(
      await main.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)
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
    const evidence = path.resolve('../../artifacts/acceptance/TC-19-009')
    mkdirSync(path.join(evidence, 'screenshots'), { recursive: true })
    const axePath = path.join(evidence, `axe-rules-form-${width}.json`)
    writeFileSync(
      axePath,
      `${JSON.stringify(
        {
          width,
          surface: 'notification-rules-form',
          violationCount: violations.length,
          violations,
        },
        null,
        2
      )}\n`
    )
    const screenshot = path.join(
      evidence,
      'screenshots',
      `rules-form-${width}.png`
    )
    await page.screenshot({ path: screenshot, fullPage: true })
    expect(violations).toEqual([])
  })
}
