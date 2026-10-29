import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-006b'
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
        routes: ['/dashboard/documents'],
        icons: ['document'],
        sizes: ['medium'],
        visibility_scopes: ['all'],
      })
    }
    if (pathname.includes('/api/dashboard/cards'))
      return json({ cards: [], has_custom: false })
    if (pathname.includes('/unread-count')) return json({ count: 0 })
    if (pathname.includes('/api/auth/alerts')) return json({ alerts: [] })
    return json([])
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

async function hideDevPortal(page: Page) {
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
}

async function openDashboard(page: Page, width: number, height: number) {
  await hideDevPortal(page)
  await installSyntheticApi(page)
  await allowSyntheticSession(page)
  await page.setViewportSize({ width, height })
  await page.goto('/dashboard')
  await expect(page.locator('#main-content')).toBeVisible({ timeout: 30_000 })
}

async function liveRegionState(page: Page) {
  return page.evaluate(() => {
    return ['tc-toast-status', 'tc-toast-alert'].map((id) => {
      const el = document.getElementById(id)
      return {
        id,
        present: Boolean(el),
        live: el?.getAttribute('aria-live') ?? '',
        inert: Boolean(el?.closest('[inert]')),
        hidden: el?.getAttribute('aria-hidden') === 'true',
        text: (el?.textContent ?? '').replace(/\s+/g, ' ').trim(),
      }
    })
  })
}

async function expectRegionsReachable(page: Page) {
  const regions = await liveRegionState(page)
  expect(regions.map((region) => region.present)).toEqual([true, true])
  expect(regions.map((region) => region.live)).toEqual(['polite', 'assertive'])
  expect(regions.map((region) => region.inert)).toEqual([false, false])
  expect(regions.map((region) => region.hidden)).toEqual([false, false])
  return regions
}

test.describe('drawer and dialog follow-ups', () => {
  test.describe.configure({ timeout: 90_000 })

  test('toast live regions stay available while a dialog or drawer is open', async ({
    page,
  }) => {
    await hideDevPortal(page)
    await page.setViewportSize({ width: 1024, height: 800 })
    await page.goto('/design-dialogs')
    await expect(
      page.getByRole('heading', { name: 'Dialogs and notifications' })
    ).toBeVisible()

    await page.getByRole('button', { name: 'Show status' }).click()
    await expect(page.locator('#tc-toast-status')).toContainText(
      'Synthetic status saved.'
    )
    await page.getByRole('button', { name: 'Rename sample' }).click()
    const rename = page.getByRole('dialog', { name: 'Rename sample record' })
    await expect(rename).toBeVisible()
    let regions = await expectRegionsReachable(page)
    expect(regions[0]?.text).toContain('Synthetic status saved.')
    expect(regions[1]?.text).not.toContain('Synthetic status saved.')
    await page.screenshot({
      path: path.join(screenshotDir, 'dialog-toast-open.png'),
    })
    await page.keyboard.press('Escape')
    await expect(rename).toBeHidden()

    await page.getByRole('button', { name: 'Show error' }).click()
    await expect(page.locator('#tc-toast-alert')).toContainText(
      'Synthetic error stayed on screen.'
    )
    await page.getByRole('button', { name: 'Open side panel' }).click()
    const sidePanel = page.getByRole('dialog', { name: 'Navigation' })
    await expect(sidePanel).toBeVisible()
    regions = await expectRegionsReachable(page)
    expect(regions[1]?.text).toContain('Synthetic error stayed on screen.')
    await page.keyboard.press('Escape')

    await openDashboard(page, 360, 800)
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await expect(page.getByRole('dialog', { name: 'Navigation' })).toBeVisible()
    await expectRegionsReachable(page)
  })

  test('resizing past 768px closes the drawer and focuses a visible target', async ({
    page,
  }) => {
    await openDashboard(page, 360, 800)
    const openNav = page.getByRole('button', { name: 'Open navigation' })
    await openNav.click()
    const dialog = page.getByRole('dialog', { name: 'Navigation' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'Home' })).toBeFocused()

    await page.setViewportSize({ width: 800, height: 800 })
    await expect(dialog).toBeHidden()
    await expect(openNav).toBeHidden()
    await expect(page.locator('#main-content')).toBeFocused()
    await expect(page.locator('[data-sidebar-placement="dock"]')).toBeVisible()
    const focusedVisible = await page.evaluate(() => {
      const el = document.activeElement
      if (!(el instanceof HTMLElement)) return false
      const style = getComputedStyle(el)
      const rect = el.getBoundingClientRect()
      return (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        rect.width > 0 &&
        rect.height > 0
      )
    })
    expect(focusedVisible).toBe(true)
    await page.screenshot({
      path: path.join(screenshotDir, 'drawer-closed-800.png'),
    })
  })

  test('a viewport of 320px and below keeps a tappable backdrop strip', async ({
    page,
  }) => {
    for (const width of [320, 300]) {
      await openDashboard(page, width, 700)
      await page.getByRole('button', { name: 'Open navigation' }).click()
      const dialog = page.getByRole('dialog', { name: 'Navigation' })
      await expect(dialog).toBeVisible()
      const panel = await dialog.boundingBox()
      expect(panel).not.toBeNull()
      expect(panel!.width).toBeLessThan(width - 24)
      expect(panel!.x + panel!.width).toBeLessThan(width - 16)

      if (width === 320) {
        await page.screenshot({
          path: path.join(screenshotDir, 'drawer-320-open.png'),
        })
        const axe = await new AxeBuilder({ page }).analyze()
        mkdirSync(evidenceDir, { recursive: true })
        writeFileSync(
          path.join(evidenceDir, 'axe-drawer-320.json'),
          `${JSON.stringify(
            {
              name: 'drawer-320',
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
        expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual(
          []
        )
      }

      await page.mouse.click(width - 8, 240)
      await expect(dialog).toBeHidden()
    }
  })
})
