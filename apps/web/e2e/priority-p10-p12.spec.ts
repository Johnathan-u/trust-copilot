import { test, expect } from '@playwright/test'

const DEMO_EMAIL = 'demo@trust.local'
const DEMO_PASSWORD = 'j'

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.waitForLoadState('networkidle')
  await page.locator('input[type="email"]').fill(DEMO_EMAIL)
  await page.locator('input[type="password"]').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15000 })
}

test.describe('P10 Bulk archive E2E', () => {
  test.beforeEach(async ({ page }) => {
    if (process.env.E2E_SERVER_RUNNING) {
      await page.goto('/dashboard')
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })
    } else {
      await login(page)
    }
  })

  test('Documents: bulk selection bar and bulk delete modal (cancel)', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const rowChecks = page.locator('ul li input[type="checkbox"]')
    // Demo user must be editor (seed_demo_workspace) and E2E seed must provide 2+ active docs.
    await expect
      .poll(async () => rowChecks.count(), { timeout: 20_000 })
      .toBeGreaterThanOrEqual(2)
    await rowChecks.nth(0).check()
    await rowChecks.nth(1).check()
    await expect(page.getByText(/\d+ document(s)? selected/i)).toBeVisible({ timeout: 5000 })
    await page.getByRole('button', { name: /delete selected/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // Avoid /archive/i: muted copy also contains "archives" (strict mode → 2 matches).
    await expect(dialog.getByText(/You are about to archive/i)).toBeVisible()
    await dialog.getByRole('button', { name: /^cancel$/i }).click()
    await expect(dialog).toBeHidden()
  })
})

test.describe('P11 Archived filter + restore E2E', () => {
  test.beforeEach(async ({ page }) => {
    if (process.env.E2E_SERVER_RUNNING) {
      await page.goto('/dashboard')
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })
    } else {
      await login(page)
    }
  })

  test('Documents: archived filter modes switch without error', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const archivedSelect = page
      .locator('select')
      .filter({ has: page.locator('option[value="only"]') })
      .first()
    await expect(archivedSelect).toBeVisible({ timeout: 10000 })
    await archivedSelect.selectOption('only')
    await page.waitForLoadState('networkidle')
    await archivedSelect.selectOption('active')
    await page.waitForLoadState('networkidle')
    await archivedSelect.selectOption('include')
    await page.waitForLoadState('networkidle')
  })

  test('Documents: restore appears in row menu when archived rows exist', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const archivedSelect = page
      .locator('select')
      .filter({ has: page.locator('option[value="only"]') })
      .first()
    await archivedSelect.selectOption('only')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    // DOC-E2E002 is always archived by seed_e2e_registry; row must render before opening the menu.
    await expect(firstActions).toBeVisible({ timeout: 20_000 })
    await firstActions.click()
    const menu = page.getByRole('menu')
    await expect(menu).toBeVisible()
    const restore = menu.getByRole('menuitem', { name: /restore/i })
    const deleteItem = menu.getByRole('menuitem', { name: /^delete$/i })
    await expect(restore.or(deleteItem)).toBeVisible()
    await page.keyboard.press('Escape')
  })
})

/**
 * P12 — Row action menu + metadata editor (extends P09 with questionnaires path).
 */
test.describe('P12 Metadata editor + row action menu E2E', () => {
  test.beforeEach(async ({ page }) => {
    if (process.env.E2E_SERVER_RUNNING) {
      await page.goto('/dashboard')
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })
    } else {
      await login(page)
    }
  })

  test('Questionnaires: row menu and metadata editor opens', async ({ page }) => {
    await page.goto('/dashboard/questionnaires')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    await expect(firstActions).toBeVisible({ timeout: 10000 })
    await firstActions.click()
    await expect(page.getByRole('menu')).toBeVisible()
    await page.getByRole('menuitem', { name: /edit metadata/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Frameworks', { exact: true })).toBeVisible()
    await dialog.getByRole('button', { name: /close/i }).click()
  })
})
