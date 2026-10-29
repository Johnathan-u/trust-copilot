import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-04-001b-web'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

const wcag21aa = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
const viewports = [
  { name: '360', width: 360, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '1440', width: 1440, height: 900 },
] as const

const hiddenDetail = 'HIDDEN_CAP_VALUE'
const invitationCopy =
  'Access is set up by invitation. Ask your workspace administrator for an invite.'
const unavailableCopy = 'Workspace creation could not be checked. Try again.'

type PolicyMode = 'allowed' | 'denied' | 'error' | 'extra' | 'hold' | 'retry'

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

function pathnameOf(url: string) {
  return new URL(url).pathname.replace(/\/$/, '')
}

function isCreationPolicy(url: string, method: string) {
  return (
    method === 'GET' && pathnameOf(url) === '/api/workspaces/creation-policy'
  )
}

function isWorkspaceCreate(url: string, method: string) {
  return method === 'POST' && pathnameOf(url) === '/api/workspaces'
}

async function fulfillJson(
  route: Route,
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

type CreateMock = {
  status: number
  detail: string
  retryAfter?: string
  hold?: Promise<void>
}

async function installApi(
  page: Page,
  options: {
    policy: PolicyMode
    held?: Promise<void>
    create?: CreateMock
  }
) {
  const creates: string[] = []
  const consoleText: string[] = []
  let policyReads = 0
  page.on('console', (message) => {
    consoleText.push(message.text())
  })
  page.on('request', (request) => {
    if (isWorkspaceCreate(request.url(), request.method())) {
      creates.push(request.url())
    }
  })
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const pathname = pathnameOf(request.url())
    if (isCreationPolicy(request.url(), request.method())) {
      policyReads += 1
      if (options.policy === 'hold' && options.held) await options.held
      if (
        options.policy === 'error' ||
        (options.policy === 'retry' && policyReads === 1)
      ) {
        await fulfillJson(
          route,
          { detail: hiddenDetail, admin_cap: 86400 },
          503
        )
        return
      }
      if (options.policy === 'extra') {
        await fulfillJson(route, {
          can_create_workspace: true,
          admin_cap: hiddenDetail,
        })
        return
      }
      await fulfillJson(route, {
        can_create_workspace: options.policy !== 'denied',
      })
      return
    }
    if (isWorkspaceCreate(request.url(), request.method())) {
      if (options.create?.hold) await options.create.hold
      const headers: Record<string, string> = {}
      if (options.create?.retryAfter != null) {
        headers['Retry-After'] = options.create.retryAfter
      }
      await fulfillJson(
        route,
        { detail: options.create?.detail ?? hiddenDetail },
        options.create?.status ?? 500,
        headers
      )
      return
    }
    if (pathname === '/api/auth/me') {
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
    if (pathname === '/api/auth/switch-workspace') {
      await fulfillJson(route, {
        workspace_id: 7,
        workspace_name: 'Synthetic Workspace',
        workspace_slug: 'synthetic',
        role: 'admin',
      })
      return
    }
    await fulfillJson(route, {})
  })
  return { creates, consoleText }
}

async function expectNoLeak(page: Page, consoleText: string[]) {
  const snapshot = await page.evaluate(() => {
    const text = document.body.innerText
    const attrs = Array.from(document.body.querySelectorAll('*'))
      .flatMap((el) =>
        Array.from(el.attributes).map((attr) => `${attr.name}=${attr.value}`)
      )
      .join('\n')
    return `${text}\n${attrs}`
  })
  expect(snapshot).not.toContain(hiddenDetail)
  expect(snapshot).not.toContain('admin_cap')
  expect(snapshot).not.toContain('86400')
  expect(snapshot).not.toMatch(/per hour/i)
  const logs = consoleText.join('\n')
  expect(logs).not.toContain(hiddenDetail)
  expect(logs).not.toContain('admin_cap')
  expect(logs).not.toContain('86400')
  expect(logs).not.toMatch(/per hour/i)
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
  const serious = axe.violations.filter(
    (item) => item.impact === 'critical' || item.impact === 'serious'
  )
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
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([])
  expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual([])
}

async function captureState(page: Page, include: string, slug: string) {
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

async function openSettings(
  page: Page,
  policy: PolicyMode,
  held?: Promise<void>
) {
  const tracked = await installApi(page, { policy, held })
  await quietDevOverlay(page)
  await allowSyntheticSession(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/dashboard/settings')
  return tracked
}

test.describe('workspace creation policy', () => {
  test.describe.configure({ timeout: 120_000 })

  test('settings shows the form when creation is allowed', async ({ page }) => {
    const tracked = await openSettings(page, 'allowed')
    const section = page.getByTestId('settings-create-workspace')
    await expect(section).toBeVisible()
    await expect(section.getByLabel('Workspace name')).toBeVisible()
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeVisible()
    await expect(page.getByTestId('workspace-creation-denied')).toHaveCount(0)
    await expect(
      page.getByTestId('workspace-creation-unavailable')
    ).toHaveCount(0)
    await page.getByRole('button', { name: /Search or jump/ }).click()
    await expect(
      page.getByRole('option', { name: 'Create workspace' })
    ).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(
      page.getByRole('dialog', { name: 'Command palette' })
    ).toHaveCount(0)
    await expectNoLeak(page, tracked.consoleText)
    expect(tracked.creates).toEqual([])
    await captureState(
      page,
      '[data-testid="settings-create-workspace"]',
      'settings-allowed'
    )
  })

  test('settings hides creation when the policy is false', async ({ page }) => {
    const tracked = await openSettings(page, 'denied')
    const denied = page.getByTestId('workspace-creation-denied')
    await expect(denied).toBeVisible()
    await expect(denied).toContainText(invitationCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    await expect(page.getByTestId('settings-create-workspace')).toHaveCount(0)
    await page.getByRole('button', { name: /Search or jump/ }).click()
    await expect(
      page.getByRole('option', { name: 'Create workspace' })
    ).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(
      page.getByRole('dialog', { name: 'Command palette' })
    ).toHaveCount(0)
    await expectNoLeak(page, tracked.consoleText)
    expect(tracked.creates).toEqual([])
    await captureState(
      page,
      '[data-testid="workspace-creation-denied"]',
      'settings-denied'
    )
  })

  test('settings hides creation when the policy cannot be read and retry can show the form', async ({
    page,
  }) => {
    const tracked = await openSettings(page, 'retry')
    const unavailable = page.getByTestId('workspace-creation-unavailable')
    await expect(unavailable).toBeVisible()
    await expect(unavailable).toContainText(unavailableCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    await expectNoLeak(page, tracked.consoleText)
    await captureState(
      page,
      '[data-testid="workspace-creation-unavailable"]',
      'settings-unavailable'
    )
    await page.setViewportSize({ width: 1440, height: 900 })
    await unavailable.getByRole('button', { name: 'Try again' }).click()
    await expect(page.getByTestId('settings-create-workspace')).toBeVisible()
    await expect(page.getByLabel('Workspace name')).toBeVisible()
    expect(tracked.creates).toEqual([])
  })

  test('settings does not render the form while the policy read is pending', async ({
    page,
  }) => {
    let release = () => {}
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    const tracked = await openSettings(page, 'hold', held)
    await expect(page.getByTestId('workspace-creation-loading')).toBeVisible()
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    await expect(page.getByTestId('settings-create-workspace')).toHaveCount(0)
    release()
    await expect(page.getByLabel('Workspace name')).toBeVisible()
    expect(tracked.creates).toEqual([])
  })

  test('an unexpected policy field hides creation and is not shown', async ({
    page,
  }) => {
    const tracked = await openSettings(page, 'extra')
    await expect(
      page.getByTestId('workspace-creation-unavailable')
    ).toBeVisible()
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expectNoLeak(page, tracked.consoleText)
    expect(tracked.creates).toEqual([])
  })

  test('a refused submit still explains invitation access', async ({
    page,
  }) => {
    const tracked = await installApi(page, {
      policy: 'allowed',
      create: { status: 403, detail: hiddenDetail },
    })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard/settings')
    const section = page.getByTestId('settings-create-workspace')
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    await expect(notice).toHaveAttribute('data-notice-kind', 'invitation')
    await expect(notice).toContainText(invitationCopy)
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeDisabled()
    await expectNoLeak(page, tracked.consoleText)
    expect(tracked.creates).toHaveLength(1)
  })

  test('a conflict submit still explains the maximum and leaves the action available', async ({
    page,
  }) => {
    const tracked = await installApi(page, {
      policy: 'allowed',
      create: { status: 409, detail: hiddenDetail },
    })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard/settings')
    const section = page.getByTestId('settings-create-workspace')
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    await expect(notice).toContainText(
      'You have reached the maximum number of workspaces you can administer.'
    )
    await expect(
      section.getByRole('button', { name: 'Create workspace' })
    ).toBeEnabled()
    await expectNoLeak(page, tracked.consoleText)
  })

  test('too many attempts still shows a readable wait and blocks the action', async ({
    page,
  }) => {
    const tracked = await installApi(page, {
      policy: 'allowed',
      create: { status: 429, detail: hiddenDetail, retryAfter: '120' },
    })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard/settings')
    const section = page.getByTestId('settings-create-workspace')
    await expect(section).toBeVisible()
    await page.clock.install()
    await section.getByLabel('Workspace name').fill('Northwind')
    await section.getByRole('button', { name: 'Create workspace' }).click()
    const notice = section.getByTestId('workspace-create-notice')
    const submit = section.getByRole('button', { name: 'Create workspace' })
    await expect(notice).toContainText('Wait 2 minutes before trying again.')
    await expect(submit).toBeDisabled()
    await expectNoLeak(page, tracked.consoleText)
    await page.clock.fastForward(120_000)
    await expect(submit).toBeEnabled()
    await expect(notice).toContainText('You can try again now.')
  })

  test('onboarding shows the form only when creation is allowed', async ({
    page,
  }) => {
    let release = () => {}
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let releaseCreate = () => {}
    const createHeld = new Promise<void>((resolve) => {
      releaseCreate = resolve
    })
    const tracked = await installApi(page, {
      policy: 'hold',
      held,
      create: { status: 200, detail: '', hold: createHeld },
    })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/onboarding')
    await expect(
      page.getByRole('heading', { name: 'Welcome to Trust Copilot', level: 1 })
    ).toBeVisible()
    await expect(page.getByTestId('workspace-creation-loading')).toBeVisible()
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    release()
    const form = page.getByTestId('workspace-creation-form')
    await expect(form.getByLabel('Workspace name')).toBeVisible()
    await expectNoLeak(page, tracked.consoleText)
    await captureState(
      page,
      '[data-testid="workspace-creation-form"]',
      'onboarding-allowed'
    )
    await page.setViewportSize({ width: 1440, height: 900 })
    await form.getByLabel('Workspace name').fill('Northwind')
    await form.getByRole('button', { name: 'Create workspace' }).click()
    await expect(form.getByRole('button', { name: 'Creating…' })).toBeVisible()
    await expect(form.getByRole('button', { name: 'Created' })).toHaveCount(0)
    expect(tracked.creates).toHaveLength(1)
    releaseCreate()
    await expect(page).toHaveURL(/\/dashboard/)
    await expectNoLeak(page, tracked.consoleText)
  })

  test('onboarding explains invitation access when creation is not allowed', async ({
    page,
  }) => {
    const tracked = await installApi(page, { policy: 'denied' })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/onboarding')
    const notice = page.getByTestId('workspace-invitation-notice')
    await expect(notice).toContainText(invitationCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    expect(tracked.creates).toEqual([])
    await expectNoLeak(page, tracked.consoleText)
    await captureState(
      page,
      '[data-testid="workspace-invitation"]',
      'onboarding-denied'
    )
  })

  test('onboarding hides the form when the policy cannot be read', async ({
    page,
  }) => {
    const tracked = await installApi(page, { policy: 'error' })
    await quietDevOverlay(page)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/onboarding')
    await expect(
      page.getByRole('heading', { name: 'Welcome to Trust Copilot', level: 1 })
    ).toBeVisible()
    await expect(
      page.getByTestId('workspace-creation-unavailable')
    ).toContainText(unavailableCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeEnabled()
    await expect(page.getByRole('link', { name: 'Back' })).toHaveAttribute(
      'href',
      '/'
    )
    expect(tracked.creates).toEqual([])
    await expectNoLeak(page, tracked.consoleText)
    await captureState(page, 'main', 'onboarding-unavailable')
  })

  test('checkout keeps the invitation when creation is allowed', async ({
    page,
  }) => {
    const tracked = await installApi(page, { policy: 'allowed' })
    await quietDevOverlay(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/checkout')
    const notice = page.getByTestId('workspace-invitation-notice')
    await expect(notice).toContainText(invitationCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Back' })).toHaveAttribute(
      'href',
      '/pricing'
    )
    expect(tracked.creates).toEqual([])
    await expectNoLeak(page, tracked.consoleText)
    await captureState(
      page,
      '[data-testid="workspace-invitation"]',
      'checkout-allowed'
    )
  })

  test('checkout explains invitation access when creation is not allowed', async ({
    page,
  }) => {
    const tracked = await installApi(page, { policy: 'denied' })
    await quietDevOverlay(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/checkout')
    await expect(page.getByTestId('workspace-invitation-notice')).toContainText(
      invitationCopy
    )
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    expect(tracked.creates).toEqual([])
    await expectNoLeak(page, tracked.consoleText)
  })

  test('checkout hides creation when the policy cannot be read', async ({
    page,
  }) => {
    const tracked = await installApi(page, { policy: 'error' })
    await quietDevOverlay(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/checkout')
    await expect(
      page.getByRole('heading', { name: 'Trust Copilot', level: 1 })
    ).toBeVisible()
    await expect(
      page.getByTestId('workspace-creation-unavailable')
    ).toContainText(unavailableCopy)
    await expect(page.getByLabel('Workspace name')).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Back' })).toHaveAttribute(
      'href',
      '/pricing'
    )
    expect(tracked.creates).toEqual([])
    await expectNoLeak(page, tracked.consoleText)
    await captureState(page, 'main', 'checkout-unavailable')
  })
})
