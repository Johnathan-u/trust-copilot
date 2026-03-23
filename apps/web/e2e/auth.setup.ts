/**
 * Auth setup: log in as demo user and save storage state for reuse.
 * Runs in the `setup` project when E2E_SERVER_RUNNING=1 (see playwright.config.ts).
 */
import * as fs from 'fs'
import * as path from 'path'
import { test as setup, expect } from '@playwright/test'

const DEMO_EMAIL = 'demo@trust.local'
const DEMO_PASSWORD = 'j'
const AUTH_FILE = 'e2e/.auth/user.json'

setup('authenticate as demo user', async ({ page }) => {
  fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true })

  await page.goto('/login', { waitUntil: 'load' })
  await page.locator('input[type="email"]').waitFor({ state: 'visible' })
  await page.locator('input[type="password"]').waitFor({ state: 'visible' })
  // Controlled inputs: clear then type so React state always matches (fill alone can race hydration).
  await page.locator('input[type="email"]').click()
  await page.locator('input[type="email"]').fill('')
  await page.locator('input[type="email"]').pressSequentially(DEMO_EMAIL, { delay: 5 })
  await page.locator('input[type="password"]').click()
  await page.locator('input[type="password"]').fill('')
  await page.locator('input[type="password"]').pressSequentially(DEMO_PASSWORD, { delay: 5 })

  const signIn = page.getByRole('button', { name: 'Sign in' })
  await signIn.waitFor({ state: 'visible' })
  await expect(signIn).toBeEnabled({ timeout: 60_000 })
  await signIn.click()
  // Prefer URL over waitForResponse — client fetch URL shape can vary; dashboard is the success signal.
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 120_000 })
  await page.context().storageState({ path: AUTH_FILE })
})
