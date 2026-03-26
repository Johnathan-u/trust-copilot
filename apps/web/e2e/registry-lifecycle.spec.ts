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

/**
 * P09 — Frontend registry lifecycle E2E (documents, questionnaires, trust requests UX smoke).
 */
test.describe('P09 Registry lifecycle E2E', () => {
  test.beforeEach(async ({ page }) => {
    if (process.env.E2E_SERVER_RUNNING) {
      await page.goto('/dashboard')
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 })
    } else {
      await login(page)
    }
  })

  test('Documents: row action menu opens and shows expected actions', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    await expect(firstActions).toBeVisible({ timeout: 10000 })
    await firstActions.click()
    await expect(page.getByRole('menu')).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /copy id/i })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /edit metadata/i })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /delete|restore/i })).toBeVisible()
  })

  test('Documents: archived filter options are present', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const select = page.locator('select').filter({ has: page.locator('option:has-text("Archived only")') }).first()
    await expect(select).toBeVisible()
    // Options may be hidden when select is closed; assert by value/count
    await expect(select.locator('option[value="active"]')).toHaveCount(1)
    await expect(select.locator('option[value="include"]')).toHaveCount(1)
    await expect(select.locator('option[value="only"]')).toHaveCount(1)
  })

  test('Questionnaires: row action menu includes Open and Copy ID', async ({ page }) => {
    await page.goto('/dashboard/questionnaires')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    await expect(firstActions).toBeVisible({ timeout: 10000 })
    await firstActions.click()
    await expect(page.getByRole('menu')).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /copy id/i })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: /^open$/i })).toBeVisible()
  })

  test('Delete preview modal: opens and shows record label when Delete clicked', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    await expect(firstActions).toBeVisible({ timeout: 10000 })
    await firstActions.click()
    await page.getByRole('menuitem', { name: /delete/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Delete record?' })).toBeVisible()
    await expect(dialog.getByText(/^ID: /)).toBeVisible()
  })

  test('Metadata editor: opens when Edit metadata clicked', async ({ page }) => {
    await page.goto('/dashboard/documents')
    await page.waitForLoadState('networkidle')
    const firstActions = page.getByRole('button', { name: /actions/i }).first()
    await expect(firstActions).toBeVisible({ timeout: 10000 })
    await firstActions.click()
    await page.getByRole('menuitem', { name: /edit metadata/i }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Frameworks', { exact: true })).toBeVisible()
  })
})
