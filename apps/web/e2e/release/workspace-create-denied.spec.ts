import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-04-001a-web'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

const wcag21aa = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: '320', width: 320, height: 800 },
] as const

const hiddenDetail = 'SERVER_DETAIL_SHOULD_NOT_APPEAR'
const salesOrigin = `http://127.0.0.1:${process.env.E2E_SALES_WEB_PORT || '3100'}`
const configuredContact =
  'mailto:owner.contact@example.com?subject=Workspace%20access'
const invitationCopy =
  'Access is set up by invitation. Ask your workspace administrator for an invite.'

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

function syntheticMe() {
  return {
    id: 42,
    email: 'synthetic.member@example.com',
    display_name: 'Synthetic Member',
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
    subscription: { status: 'active', plan: 'synthetic' },
    mfa_enrolled: true,
    mfa_required_for_workspace: false,
    workspace_auth_policy: {
      mfa_required: false,
      session_max_age_seconds: null,
    },
  }
}

function isWorkspaceCreate(url: string, method: string) {
  if (method !== 'POST') return false
  try {
    return new URL(url).pathname.replace(/\/$/, '') === '/api/workspaces'
  } catch {
    return false
  }
}

function isCreationPolicy(url: string, method: string) {
  if (method !== 'GET') return false
  try {
    return (
      new URL(url).pathname.replace(/\/$/, '') ===
      '/api/workspaces/creation-policy'
    )
  } catch {
    return false
  }
}

async function quietDevOverlay(page: Page) {
  await page.addInitScript(() => {
    const removeDevPortal = () => {
      document.querySelectorAll('nextjs-portal').forEach((el) => {
        el.remove()
      })
    }
    removeDevPortal()
    new MutationObserver(removeDevPortal).observe(document.documentElement, {
      childList: true,
      subtree: true,
    })
  })
}

async function allowSyntheticSession(page: Page) {
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
}

function trackWorkspaceCreates(page: Page) {
  const calls: string[] = []
  page.on('request', (request) => {
    if (isWorkspaceCreate(request.url(), request.method())) {
      calls.push(request.url())
    }
  })
  return calls
}

async function fulfillJson(
  route: { fulfill: (opts: object) => Promise<void> },
  body: unknown,
  status = 200,
  extraHeaders?: Record<string, string>
) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers: extraHeaders,
    body: JSON.stringify(body),
  })
}

async function installInvitationRoutes(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    if (isCreationPolicy(request.url(), request.method())) {
      await fulfillJson(route, { can_create_workspace: false })
      return
    }
    if (isWorkspaceCreate(request.url(), request.method())) {
      await fulfillJson(route, { detail: hiddenDetail }, 500)
      return
    }
    await fulfillJson(route, {})
  })
}

type WorkspaceMock = {
  status: number
  detail: string
  retryAfter?: string
}

async function installSettingsRoutes(page: Page, workspace: WorkspaceMock) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (isCreationPolicy(request.url(), request.method())) {
      await fulfillJson(route, { can_create_workspace: true })
      return
    }
    if (isWorkspaceCreate(request.url(), request.method())) {
      const headers: Record<string, string> = {}
      if (workspace.retryAfter != null)
        headers['Retry-After'] = workspace.retryAfter
      await fulfillJson(
        route,
        { detail: workspace.detail },
        workspace.status,
        headers
      )
      return
    }
    if (pathname.endsWith('/api/auth/me')) {
      await fulfillJson(route, syntheticMe())
      return
    }
    if (pathname.includes('/unread-count')) {
      await fulfillJson(route, { count: 0 })
      return
    }
    if (pathname.includes('/api/auth/alerts')) {
      await fulfillJson(route, { alerts: [] })
      return
    }
    if (pathname.includes('/api/in-app-notifications')) {
      await fulfillJson(route, { items: [] })
      return
    }
    await fulfillJson(route, {})
  })
}

async function expectNoOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1)
}

async function writeAxe(page: Page, include: string, name: string) {
  const axe = await new AxeBuilder({ page })
    .include(include)
    .withTags(wcag21aa)
    .analyze()
  writeFileSync(
    path.join(evidenceDir, `axe-${name}.json`),
    `${JSON.stringify(
      {
        name,
        violationCount: axe.violations.length,
        violations: axe.violations.map((item) => ({
          id: item.id,
          impact: item.impact,
          help: item.help,
          nodes: item.nodes.length,
        })),
      },
      null,
      2
    )}\n`
  )
  expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual([])
}

async function captureDeniedState(page: Page, include: string, slug: string) {
  for (const viewport of viewports) {
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    })
    await expectNoOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, `${slug}-${viewport.name}.png`),
      fullPage: true,
    })
    await writeAxe(page, include, `${slug}-${viewport.name}`)
  }
}

async function openInvitation(
  page: Page,
  route: '/onboarding' | '/checkout',
  origin = ''
) {
  const calls = trackWorkspaceCreates(page)
  await quietDevOverlay(page)
  await installInvitationRoutes(page)
  if (route === '/onboarding') await allowSyntheticSession(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`${origin}${route}`)
  return calls
}

test.describe('workspace creation is not offered up front', () => {
  test.describe.configure({ timeout: 120_000 })

  test('onboarding explains invitation access and does not create a workspace', async ({
    page,
  }) => {
    const calls = await openInvitation(page, '/onboarding')
    const panel = page.getByTestId('workspace-invitation')
    await expect(
      page.getByRole('heading', { name: 'Welcome to Trust Copilot', level: 1 })
    ).toBeVisible()
    const notice = page.getByTestId('workspace-invitation-notice')
    await expect(notice).toHaveAttribute('role', 'alert')
    await expect(notice).toContainText(invitationCopy)
    await expect(notice).toBeFocused()
    await expect(page.getByRole('link', { name: 'Contact sales' })).toHaveCount(
      0
    )
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeEnabled()
    await expect(page.getByRole('link', { name: 'Back' })).toHaveAttribute(
      'href',
      '/'
    )
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    expect(calls).toEqual([])
    await captureDeniedState(
      page,
      '[data-testid="workspace-invitation"]',
      'onboarding-invitation'
    )
    expect(calls).toEqual([])
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    expect(calls).toEqual([])
    await expect(panel).toHaveCount(0)
  })

  test('checkout explains invitation access and does not create a workspace', async ({
    page,
  }) => {
    const calls = await openInvitation(page, '/checkout')
    await expect(
      page.getByRole('heading', { name: 'Trust Copilot', level: 1 })
    ).toBeVisible()
    const notice = page.getByTestId('workspace-invitation-notice')
    await expect(notice).toHaveAttribute('role', 'alert')
    await expect(notice).toContainText(invitationCopy)
    await expect(notice).toBeFocused()
    await expect(page.getByRole('link', { name: 'Contact sales' })).toHaveCount(
      0
    )
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeEnabled()
    await expect(page.getByRole('link', { name: 'Back' })).toHaveAttribute(
      'href',
      '/pricing'
    )
    await expect(
      page.getByRole('button', { name: /Create workspace/ })
    ).toHaveCount(0)
    expect(calls).toEqual([])
    await captureDeniedState(
      page,
      '[data-testid="workspace-invitation"]',
      'checkout-invitation'
    )
    expect(calls).toEqual([])
    await page.getByRole('link', { name: 'Back' }).click()
    await expect(page).toHaveURL(/\/pricing/)
    expect(calls).toEqual([])
  })

  test('onboarding shows a configured contact link', async ({ page }) => {
    const calls = await openInvitation(page, '/onboarding', salesOrigin)
    const link = page.getByRole('link', { name: 'Contact sales' })
    await expect(page.getByTestId('workspace-invitation-notice')).toContainText(
      invitationCopy
    )
    await expect(link).toHaveAttribute('href', configuredContact)
    expect(calls).toEqual([])
    await captureDeniedState(
      page,
      '[data-testid="workspace-invitation"]',
      'onboarding-contact'
    )
    expect(calls).toEqual([])
  })

  test('checkout shows a configured contact link', async ({ page }) => {
    const calls = await openInvitation(page, '/checkout', salesOrigin)
    const link = page.getByRole('link', { name: 'Contact sales' })
    await expect(page.getByTestId('workspace-invitation-notice')).toContainText(
      invitationCopy
    )
    await expect(link).toHaveAttribute('href', configuredContact)
    expect(calls).toEqual([])
    await captureDeniedState(
      page,
      '[data-testid="workspace-invitation"]',
      'checkout-contact'
    )
    expect(calls).toEqual([])
  })
})

test.describe('remaining workspace creation responses', () => {
  test.describe.configure({ timeout: 120_000 })

  async function openCreate(page: Page, workspace: WorkspaceMock) {
    await quietDevOverlay(page)
    await installSettingsRoutes(page, workspace)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard/settings')
    const section = page.getByTestId('settings-create-workspace')
    await expect(section).toBeVisible()
    return section
  }

  test('a refused creation explains invitation access and disables the action', async ({
    page,
  }) => {
    const section = await openCreate(page, {
      status: 403,
      detail: hiddenDetail,
    })
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    await expect(notice).toHaveAttribute('role', 'alert')
    await expect(notice).toHaveAttribute('data-notice-kind', 'invitation')
    await expect(notice).toContainText(invitationCopy)
    await expect(
      notice.getByRole('link', { name: 'Contact sales' })
    ).toHaveCount(0)
    await expect(notice).toBeFocused()
    await expect(page.getByText(hiddenDetail)).toHaveCount(0)
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeDisabled()
    await captureDeniedState(
      page,
      '[data-testid="settings-create-workspace"]',
      'settings-403'
    )
  })

  test('a conflict says the person has reached the maximum they can administer', async ({
    page,
  }) => {
    const section = await openCreate(page, {
      status: 409,
      detail: hiddenDetail,
    })
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    await expect(notice).toHaveAttribute('role', 'alert')
    await expect(notice).toContainText(
      'You have reached the maximum number of workspaces you can administer.'
    )
    await expect(notice).toBeFocused()
    await expect(page.getByText(hiddenDetail)).toHaveCount(0)
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeEnabled()
    await captureDeniedState(
      page,
      '[data-testid="settings-create-workspace"]',
      'settings-409'
    )
  })

  test('too many attempts shows a readable wait and blocks retry until it ends', async ({
    page,
  }) => {
    const section = await openCreate(page, {
      status: 429,
      detail: hiddenDetail,
      retryAfter: '120',
    })
    await page.clock.install()
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    const submit = section.getByRole('button', { name: 'Create workspace' })
    await expect(notice).toHaveAttribute('role', 'alert')
    await expect(notice).toContainText('There were too many attempts.')
    await expect(notice).toContainText('Try again later.')
    await expect(notice).toContainText('Wait 2 minutes before trying again.')
    await expect(notice).toBeFocused()
    await expect(page.getByText(hiddenDetail)).toHaveCount(0)
    await expect(submit).toBeDisabled()
    await captureDeniedState(
      page,
      '[data-testid="settings-create-workspace"]',
      'settings-429'
    )
    await page.clock.fastForward(120_000)
    await expect(submit).toBeEnabled()
    await expect(notice).toContainText('You can try again now.')
  })

  test('any other creation failure keeps the generic message', async ({
    page,
  }) => {
    const section = await openCreate(page, {
      status: 400,
      detail: 'A workspace with this name already exists',
    })
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    await expect(section.getByTestId('workspace-create-notice')).toHaveCount(0)
    await expect(
      section.getByText('A workspace with this name already exists')
    ).toBeVisible()
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeEnabled()
  })
})
