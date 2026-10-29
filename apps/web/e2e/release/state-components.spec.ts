import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-005'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

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

const syntheticCards = [
  {
    id: 1,
    title: 'Synthetic card 1',
    description: 'Synthetic workspace shortcut. No customer content.',
    icon: 'document',
    target_route: '/dashboard/documents',
    is_builtin: true,
    is_enabled: true,
    size: 'medium',
  },
]

type CardsMode = 'ok' | 'empty' | '500' | '403' | '404' | 'offline' | 'hold'
type AlertsMode = 'empty' | '500'

let cardsMode: CardsMode = 'ok'
let alertsMode: AlertsMode = 'empty'
let sessionMode: 'ok' | '500' = 'ok'
let cardsSeq = 0
let fulfillFromId = Number.POSITIVE_INFINITY

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function isCardsPath(pathname: string) {
  return (
    pathname.includes('/api/dashboard/cards') &&
    !pathname.includes('allowed-routes')
  )
}

async function fulfillCards(route: Route) {
  if (cardsMode === 'empty') {
    return json(route, { cards: [], has_custom: false })
  }
  if (cardsMode === '500') {
    return json(route, { detail: 'Insufficient permissions' }, 500)
  }
  if (cardsMode === '403') {
    return json(route, { detail: 'Insufficient permissions' }, 403)
  }
  if (cardsMode === '404') {
    return json(route, { detail: 'Workspace not found' }, 404)
  }
  if (cardsMode === 'offline') return route.abort('internetdisconnected')
  return json(route, { cards: syntheticCards, has_custom: false })
}

async function installApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/api/auth/me')) {
      if (sessionMode === '500') {
        return json(route, { detail: 'Insufficient permissions' }, 500)
      }
      return json(route, syntheticMe)
    }
    if (pathname.includes('/api/auth/alerts')) {
      if (alertsMode === '500') {
        return json(route, { detail: 'Insufficient permissions' }, 500)
      }
      return json(route, { alerts: [] })
    }
    if (pathname.includes('/unread-count')) return json(route, { count: 0 })
    if (pathname.includes('/api/in-app-notifications')) {
      return json(route, { notifications: [] })
    }
    return json(route, {})
  })

  await page.route('**/api/dashboard/cards**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.includes('allowed-routes')) {
      return json(route, {
        routes: ['/dashboard/documents'],
        icons: ['document'],
        sizes: ['small', 'medium', 'large'],
        visibility_scopes: ['all'],
      })
    }
    if (!isCardsPath(pathname)) return fulfillCards(route)
    if (cardsMode !== 'hold') return fulfillCards(route)
    const id = ++cardsSeq
    if (id >= fulfillFromId)
      return json(route, { cards: syntheticCards, has_custom: false })
    await new Promise<void>((resolve) => {
      const timer = setInterval(() => {
        if (route.request().failure()) {
          clearInterval(timer)
          resolve()
        }
      }, 40)
    })
    try {
      await route.abort()
    } catch {
      /* The browser already aborted the hung request. */
    }
  })
}

async function openDashboard(page: Page, width = 1440, height = 900) {
  await page.addInitScript(() => {
    const removeDevPortal = () => {
      document.querySelectorAll('nextjs-portal').forEach((el) => {
        el.setAttribute('inert', '')
        el.remove()
      })
    }
    removeDevPortal()
    new MutationObserver(removeDevPortal).observe(document.documentElement, {
      childList: true,
      subtree: true,
    })
  })
  await installApi(page)
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.setViewportSize({ width, height })
  await page.goto('/dashboard')
}

async function shoot(page: Page, name: string) {
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    await page.screenshot({
      path: path.join(screenshotDir, `${name}-${width}.png`),
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 1440, height: 900 })
}

async function writeAxe(page: Page, state: string) {
  const axe = await new AxeBuilder({ page })
    .include('#main-content')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  const violations = axe.violations.map((item) => ({
    id: item.id,
    impact: item.impact,
    help: item.help,
    nodes: item.nodes.length,
  }))
  writeFileSync(
    path.join(evidenceDir, `axe-${state}.json`),
    `${JSON.stringify(
      {
        name: state,
        state,
        viewport: 1440,
        violationCount: violations.length,
        violations,
      },
      null,
      2
    )}\n`
  )
  const blocking = violations.filter(
    (item) => item.impact === 'critical' || item.impact === 'serious'
  )
  expect(blocking, JSON.stringify(violations, null, 2)).toEqual([])
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([])
}

test.describe('loading, empty, error, retry, and partial success', () => {
  test.describe.configure({ timeout: 90_000 })

  test.beforeEach(() => {
    cardsMode = 'ok'
    alertsMode = 'empty'
    sessionMode = 'ok'
    cardsSeq = 0
    fulfillFromId = Number.POSITIVE_INFINITY
  })

  test('a successful response renders the cards', async ({ page }) => {
    await openDashboard(page)
    await expect(
      page.getByRole('heading', { name: 'Synthetic card 1', level: 2 })
    ).toBeVisible()
    await expect(
      page.getByText('Synthetic Workspace', { exact: true })
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(page.locator('[data-state="error"]')).toHaveCount(0)
    await expect(page.locator('[data-state="partial"]')).toHaveCount(0)
  })

  test('an empty successful response shows an action, not an error', async ({
    page,
  }) => {
    cardsMode = 'empty'
    await openDashboard(page)
    const empty = page.locator('[data-state="empty"]')
    await expect(
      empty.getByRole('heading', { name: 'No shortcuts yet', level: 2 })
    ).toBeVisible()
    const action = empty.getByRole('button', { name: 'Open documents' })
    await expect(action).toBeVisible()
    await expect(page.locator('[data-state="error"]')).toHaveCount(0)
    await page.locator('#main-content').focus()
    for (let step = 0; step < 10; step += 1) {
      if (await action.evaluate((el) => el === document.activeElement)) break
      await page.keyboard.press('Tab')
    }
    await expect(action).toBeFocused()
    await writeAxe(page, 'empty')
    await shoot(page, 'empty')
  })

  test('a 500 response is an error with retry, not an empty list', async ({
    page,
  }) => {
    cardsMode = '500'
    await openDashboard(page)
    const alert = page.locator('#main-content').getByRole('alert')
    await expect(
      alert.getByRole('heading', { name: 'Something went wrong', level: 2 })
    ).toBeVisible()
    await expect(alert).toHaveAttribute('data-failure', 'server')
    await expect(page.getByText('Insufficient permissions')).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'Synthetic card 1' })
    ).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'Something went wrong', level: 2 })
    ).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Try again' })).toBeFocused()
    await expect(
      page.getByText('Synthetic Workspace', { exact: true })
    ).toBeVisible()
    await writeAxe(page, 'error')
    await shoot(page, 'error')
  })

  test('an aborted route renders the offline state', async ({ page }) => {
    cardsMode = 'offline'
    await openDashboard(page)
    const alert = page.locator('#main-content').getByRole('alert')
    await expect(
      alert.getByRole('heading', { name: 'Offline', level: 2 })
    ).toBeVisible()
    await expect(alert).toHaveAttribute('data-failure', 'offline')
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  })

  test('a 403 response uses neutral copy', async ({ page }) => {
    cardsMode = '403'
    await openDashboard(page)
    const alert = page.locator('#main-content').getByRole('alert')
    await expect(
      alert.getByRole('heading', {
        name: 'This section is not available',
        level: 2,
      })
    ).toBeVisible()
    await expect(alert).toHaveAttribute('data-failure', 'forbidden')
    await expect(page.locator('#main-content')).not.toContainText(/permission/i)
    await expect(page.locator('#main-content')).not.toContainText(/403/)
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
  })

  test('a 404 response is distinct from an empty list', async ({ page }) => {
    cardsMode = '404'
    await openDashboard(page)
    const alert = page.locator('#main-content').getByRole('alert')
    await expect(
      alert.getByRole('heading', { name: 'We could not find that', level: 2 })
    ).toBeVisible()
    await expect(alert).toHaveAttribute('data-failure', 'not_found')
    await expect(page.getByText('Workspace not found')).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
  })

  test('a hung request leaves the skeleton and retry succeeds', async ({
    page,
  }) => {
    cardsMode = 'hold'
    await openDashboard(page)
    await expect(page.locator('[data-state="loading"]')).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'This is taking longer than usual' })
    ).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('[data-state="loading"]')).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'This is taking longer than usual' })
    ).toBeFocused()
    await page.keyboard.press('Tab')
    const retry = page.getByRole('button', { name: 'Try again' })
    await expect(retry).toBeFocused()
    await writeAxe(page, 'timeout')
    await shoot(page, 'timeout')
    fulfillFromId = cardsSeq + 1
    await retry.click()
    await expect(
      page.getByRole('heading', { name: 'Synthetic card 1', level: 2 })
    ).toBeVisible()
    await expect(page.locator('[data-state="slow"]')).toHaveCount(0)
    await expect(page.locator('[data-state="error"]')).toHaveCount(0)
  })

  test('one failed section keeps the sections that loaded', async ({
    page,
  }) => {
    alertsMode = '500'
    await openDashboard(page)
    await expect(
      page.getByRole('heading', { name: "Some sections didn't load", level: 2 })
    ).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Synthetic card 1', level: 2 })
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Try again: Security notices' })
    ).toBeVisible()
    await expect(page.getByText('Insufficient permissions')).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(page.locator('[data-state="partial"]')).toBeVisible()
    await shoot(page, 'partial')
  })

  test('a failed session does not render an empty workspace', async ({
    page,
  }) => {
    sessionMode = '500'
    await openDashboard(page)
    await expect(
      page.getByRole('heading', { name: 'Something went wrong', level: 1 })
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Back to login' })
    ).toBeVisible()
    await expect(
      page.getByText('Synthetic Workspace', { exact: true })
    ).toHaveCount(0)
    await expect(
      page.getByRole('heading', { name: 'No shortcuts yet' })
    ).toHaveCount(0)
    await expect(page.locator('[data-sidebar-workspace]')).toHaveCount(0)
    await expect(page.getByText('Insufficient permissions')).toHaveCount(0)
  })
})
