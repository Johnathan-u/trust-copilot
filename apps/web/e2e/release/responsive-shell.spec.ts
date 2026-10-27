import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-006'
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

const syntheticCards = Array.from({ length: 18 }, (_, index) => ({
  id: index + 1,
  title: `Synthetic card ${index + 1}`,
  description: 'Synthetic workspace shortcut. No customer content.',
  icon: 'document',
  target_route: '/dashboard/documents',
  is_builtin: true,
  is_enabled: true,
  size: 'medium',
}))

type ThemeName = 'dark' | 'light'

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

async function installSyntheticApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    const json = (body: unknown) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      })
    if (pathname.endsWith('/api/auth/me')) return json(syntheticMe)
    if (pathname.includes('/api/dashboard/cards/allowed-routes')) {
      return json({
        routes: [
          '/dashboard/documents',
          '/dashboard/questionnaires',
          '/dashboard/review',
        ],
        icons: ['document', 'questionnaire', 'check'],
        sizes: ['small', 'medium', 'large'],
        visibility_scopes: ['all', 'admin'],
      })
    }
    if (pathname.includes('/api/dashboard/cards'))
      return json({ cards: syntheticCards, has_custom: false })
    if (pathname.includes('/unread-count')) return json({ count: 0 })
    if (pathname.includes('/api/auth/alerts')) return json({ alerts: [] })
    if (pathname.includes('/oauth/providers'))
      return json({
        google: false,
        github: false,
        microsoft: false,
        sso: false,
        idme: false,
      })
    return json([])
  })
}

async function applyTheme(page: Page) {
  await page.addInitScript(() => {
    localStorage.removeItem('sidebar_compliance')
    localStorage.removeItem('sidebar_admin')
    // Next's dev indicator is a focusable control that is not part of the
    // product. Remove it so keyboard and axe checks see the shell itself.
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
    window.setInterval(removeDevPortal, 50)
  })
}

async function showTheme(page: Page, theme: ThemeName) {
  await page.evaluate((value) => {
    document.documentElement.setAttribute('data-theme', value)
  }, theme)
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

async function openShell(
  page: Page,
  theme: ThemeName,
  width: number,
  height: number,
  path = '/dashboard'
) {
  await applyTheme(page)
  await installSyntheticApi(page)
  await allowSyntheticSession(page)
  await page.setViewportSize({ width, height })
  await page.goto(path)
  await showTheme(page, theme)
  await expect(page.locator('#main-content')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
}

async function expectNoPageOverflow(page: Page) {
  const overflow = await page.evaluate(() => ({
    scroll: Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth
    ),
    client: document.documentElement.clientWidth,
  }))
  expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1)
}

async function writeAxe(page: Page, name: string, include?: string) {
  let builder = new AxeBuilder({ page })
  if (include) builder = builder.include(include)
  const axe = await builder.analyze()
  writeFileSync(
    path.join(evidenceDir, `axe-${name}.json`),
    JSON.stringify(
      {
        name,
        include: include ?? 'page',
        violationCount: axe.violations.length,
        violations: axe.violations.map((item) => ({
          id: item.id,
          impact: item.impact,
          help: item.help,
          nodes: item.nodes.slice(0, 5).map((node) => ({
            target: node.target,
            html: node.html.slice(0, 240),
            failureSummary: node.failureSummary,
          })),
        })),
      },
      null,
      2
    ) + '\n'
  )
  expect(
    axe.violations,
    JSON.stringify(axe.violations.map((item) => item.id))
  ).toEqual([])
}

test.describe('responsive application shell', () => {
  test.describe.configure({ timeout: 120_000 })

  test('360px drawer is keyboard accessible and does not squeeze the page', async ({
    page,
  }) => {
    await openShell(page, 'dark', 360, 800)
    const openNav = page.getByRole('button', { name: 'Open navigation' })
    const main = page.locator('#main-content')
    await expect(openNav).toBeVisible()
    await expect(page.locator('[data-sidebar-placement="dock"]')).toBeHidden()
    await expectNoPageOverflow(page)
    const closedMain = await main.boundingBox()
    expect(closedMain?.width ?? 0).toBeGreaterThan(300)

    await openNav.focus()
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: 'Navigation' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
    await expect(dialog.getByRole('link', { name: 'Home' })).toHaveAttribute(
      'aria-current',
      'page'
    )
    await expect(
      dialog.getByRole('button', { name: 'Compliance' })
    ).toHaveAttribute('aria-expanded', 'false')

    await page.keyboard.press('Shift+Tab')
    await expect(dialog.getByRole('button', { name: 'Admin' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()

    await dialog.getByRole('button', { name: 'Compliance' }).focus()
    await page.keyboard.press('Enter')
    await expect(
      dialog.getByRole('button', { name: 'Compliance' })
    ).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Tab')
    await expect(dialog.getByRole('link', { name: 'Coverage' })).toBeFocused()

    await dialog.getByRole('link', { name: 'Documents' }).focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/dashboard\/documents$/, { timeout: 30_000 })
    await expect(dialog).toBeHidden()
    await expect(openNav).toBeFocused()

    await page.keyboard.press('Enter')
    await expect(dialog).toBeVisible()
    await expect(
      dialog.getByRole('link', { name: 'Documents' })
    ).toHaveAttribute('aria-current', 'page')
    await expect(
      dialog.getByRole('link', { name: 'Home' })
    ).not.toHaveAttribute('aria-current', 'page')
    await expectNoPageOverflow(page)
    const openMain = await main.boundingBox()
    expect(openMain?.width ?? 0).toBeGreaterThan(300)

    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(openNav).toBeFocused()

    await page.goto('/dashboard')
    await showTheme(page, 'dark')
    await expect(
      page.getByRole('heading', { name: 'Dashboard', level: 1 })
    ).toBeVisible()
    await expectNoPageOverflow(page)

    await page.screenshot({
      path: path.join(screenshotDir, 'shell-dark-360-closed.png'),
    })
    await openNav.click()
    await expect(dialog).toBeVisible()
    await page.screenshot({
      path: path.join(screenshotDir, 'shell-dark-360-open.png'),
    })
    await writeAxe(page, 'auth-dark-360-open')
    await page.keyboard.press('Escape')
    await writeAxe(page, 'auth-dark-360-closed')
  })

  for (const viewport of [
    { name: '768', width: 768, height: 1024, minSidebar: 200, maxSidebar: 240 },
    {
      name: '1440',
      width: 1440,
      height: 900,
      minSidebar: 270,
      maxSidebar: 290,
    },
  ] as const) {
    test(`${viewport.name}px keeps the docked sidebar, sticky header and reflow`, async ({
      page,
    }) => {
      await openShell(page, 'dark', viewport.width, viewport.height)
      await expect(
        page.getByRole('button', { name: 'Open navigation' })
      ).toBeHidden()
      await expect(
        page.getByRole('dialog', { name: 'Navigation' })
      ).toHaveCount(0)

      const header = page.locator('header').first()
      const sidebar = page.locator('[data-sidebar-placement="dock"]')
      const main = page.locator('#main-content')
      await expect(sidebar).toBeVisible()
      await expect(sidebar.getByRole('link', { name: 'Home' })).toHaveAttribute(
        'aria-current',
        'page'
      )

      const headerBox = await header.boundingBox()
      const sideBox = await sidebar.boundingBox()
      const mainBox = await main.boundingBox()
      expect(headerBox).not.toBeNull()
      expect(sideBox).not.toBeNull()
      expect(mainBox).not.toBeNull()
      expect(headerBox!.y).toBeLessThanOrEqual(2)
      expect(sideBox!.width).toBeGreaterThanOrEqual(viewport.minSidebar)
      expect(sideBox!.width).toBeLessThanOrEqual(viewport.maxSidebar)
      expect(sideBox!.x + sideBox!.width).toBeLessThanOrEqual(mainBox!.x + 1)
      expect(sideBox!.y).toBeGreaterThanOrEqual(
        headerBox!.y + headerBox!.height - 1
      )

      const scrollable = await main.evaluate(
        (el) => el.scrollHeight > el.clientHeight + 8
      )
      expect(scrollable).toBe(true)
      await main.evaluate((el) => {
        el.scrollTop = 480
      })
      const headerAfter = await header.boundingBox()
      const sideAfter = await sidebar.boundingBox()
      expect(headerAfter!.y).toBeLessThanOrEqual(2)
      expect(sideAfter!.y).toBeGreaterThanOrEqual(
        headerAfter!.y + headerAfter!.height - 1
      )
      await expectNoPageOverflow(page)

      if (viewport.name === '1440') {
        await page.evaluate(() => {
          document.querySelectorAll('nextjs-portal').forEach((el) => {
            el.setAttribute('inert', '')
            el.remove()
          })
        })
        await page.keyboard.press('Tab')
        await expect(
          page.getByRole('link', { name: 'Skip to main content' })
        ).toBeFocused()
        await page.keyboard.press('Enter')
        await expect(main).toBeFocused()
        await expect(
          page
            .getByRole('navigation', { name: 'Primary' })
            .getByRole('link', { name: 'Home' })
        ).toHaveAttribute('aria-current', 'page')
        const documents = sidebar.getByRole('link', { name: 'Documents' })
        await documents.focus()
        await page.keyboard.press('Enter')
        await expect(page).toHaveURL(/\/dashboard\/documents$/, {
          timeout: 30_000,
        })
        await expect(
          sidebar.getByRole('link', { name: 'Documents' })
        ).toHaveAttribute('aria-current', 'page')
        await page.goto('/dashboard')
        await expect(
          page.getByRole('heading', { name: 'Dashboard', level: 1 })
        ).toBeVisible()
      }

      await page.screenshot({
        path: path.join(screenshotDir, `shell-dark-${viewport.name}.png`),
      })
      await writeAxe(page, `auth-dark-${viewport.name}`)
    })
  }

  test('200% zoom of a 1440px frame reflows to the drawer instead of overflowing', async ({
    page,
  }) => {
    await openShell(page, 'dark', 720, 450)
    await expect(
      page.getByRole('button', { name: 'Open navigation' })
    ).toBeVisible()
    await expect(page.locator('[data-sidebar-placement="dock"]')).toBeHidden()
    await expectNoPageOverflow(page)
    const main = await page.locator('#main-content').boundingBox()
    expect(main?.width ?? 0).toBeGreaterThan(600)
  })

  test('light theme shell passes axe and captures mobile open and closed states', async ({
    page,
  }) => {
    await openShell(page, 'light', 1440, 900)
    await expect(page.locator('[data-sidebar-placement="dock"]')).toBeVisible()
    await expectNoPageOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'shell-light-1440.png'),
    })
    await writeAxe(page, 'auth-light-1440')

    await page.setViewportSize({ width: 768, height: 1024 })
    await expect(page.locator('[data-sidebar-placement="dock"]')).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Open navigation' })
    ).toBeHidden()
    await expectNoPageOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'shell-light-768.png'),
    })
    await writeAxe(page, 'auth-light-768')

    await page.setViewportSize({ width: 360, height: 800 })
    const openNav = page.getByRole('button', { name: 'Open navigation' })
    await expect(openNav).toBeVisible()
    await expectNoPageOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'shell-light-360-closed.png'),
    })
    await writeAxe(page, 'auth-light-360-closed')
    await openNav.click()
    const dialog = page.getByRole('dialog', { name: 'Navigation' })
    await expect(dialog).toBeVisible()
    await page.screenshot({
      path: path.join(screenshotDir, 'shell-light-360-open.png'),
    })
    await writeAxe(page, 'auth-light-360-open')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(openNav).toBeFocused()
  })
})

test.describe('public layouts', () => {
  test.describe.configure({ timeout: 120_000 })

  for (const theme of ['dark', 'light'] as const) {
    test(`${theme} login has no axe violations or page overflow`, async ({
      page,
    }) => {
      await applyTheme(page)
      await installSyntheticApi(page)
      for (const viewport of [
        { name: '360', width: 360, height: 800 },
        { name: '768', width: 768, height: 1024 },
        { name: '1440', width: 1440, height: 900 },
      ]) {
        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        })
        await page.goto('/login')
        await showTheme(page, theme)
        await expect(
          page.getByRole('heading', { name: 'Trust Copilot' })
        ).toBeVisible()
        await expect(
          page.getByRole('link', { name: 'Sign in with Google' })
        ).toHaveCount(0)
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
        await expectNoPageOverflow(page)
        await page.screenshot({
          path: path.join(
            screenshotDir,
            `public-login-${theme}-${viewport.name}.png`
          ),
        })
        await writeAxe(page, `public-login-${theme}-${viewport.name}`)
      }
    })
  }

  test('marketing and onboarding pages do not overflow at 360px', async ({
    page,
  }) => {
    await applyTheme(page)
    await page.setViewportSize({ width: 360, height: 800 })
    await page.goto('/')
    await showTheme(page, 'dark')
    await expect(
      page.getByRole('link', { name: 'Trust Copilot' }).first()
    ).toBeVisible()
    await expectNoPageOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'public-home-dark-360.png'),
    })

    await allowSyntheticSession(page)
    await page.goto('/onboarding')
    await showTheme(page, 'dark')
    await expect(
      page.getByRole('heading', { name: 'Welcome to Trust Copilot' })
    ).toBeVisible()
    await expectNoPageOverflow(page)
    await page.screenshot({
      path: path.join(screenshotDir, 'public-onboarding-dark-360.png'),
    })
  })
})
