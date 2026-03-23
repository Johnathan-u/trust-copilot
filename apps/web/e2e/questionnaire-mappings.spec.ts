import { test, expect, type Page } from '@playwright/test'

const DEMO_EMAIL = 'demo@trust.local'
const DEMO_PASSWORD = 'j'

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'load' })
  await page.locator('input[type="email"]').waitFor({ state: 'visible' })
  await page.locator('input[type="password"]').waitFor({ state: 'visible' })
  await page.locator('input[type="email"]').click()
  await page.locator('input[type="email"]').fill('')
  await page.locator('input[type="email"]').pressSequentially(DEMO_EMAIL, { delay: 5 })
  await page.locator('input[type="password"]').click()
  await page.locator('input[type="password"]').fill('')
  await page.locator('input[type="password"]').pressSequentially(DEMO_PASSWORD, { delay: 5 })
  const signIn = page.getByRole('button', { name: 'Sign in' })
  await signIn.waitFor({ state: 'visible' })
  await expect(signIn).toBeEnabled({ timeout: 10000 })
  await signIn.click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30000 })
}

test.describe('Questionnaire policy gap mapping flow', () => {
  test('generate, approve, reject, edit, regenerate, persist', async ({ page }) => {
    await login(page)

    // Find a parsed questionnaire with >=3 questions via API
    const meRes = await page.request.get('/api/auth/me')
    const me = await meRes.json()
    const wsId = me.workspace_id

    const qnrRes = await page.request.get(`/api/questionnaires/?workspace_id=${wsId}`)
    const qnrs = await qnrRes.json()
    const parsed = (Array.isArray(qnrs) ? qnrs : []).filter(
      (q: { status: string; deleted_at?: string | null }) => q.status === 'parsed' && !q.deleted_at
    )
    test.skip(parsed.length === 0, 'No parsed questionnaires — seed data required')

    let targetId: number | null = null
    for (const q of parsed) {
      const detRes = await page.request.get(`/api/questionnaires/${q.id}?workspace_id=${wsId}`)
      if (!detRes.ok()) continue
      const det = await detRes.json()
      if (det.questions && det.questions.length >= 3) {
        targetId = q.id
        break
      }
    }
    test.skip(targetId === null, 'No questionnaire with >=3 parsed questions found')

    // Reset all existing mappings to 'suggested' for clean state
    const existingRes = await page.request.get(
      `/api/questionnaires/${targetId}/mappings?workspace_id=${wsId}`
    )
    if (existingRes.ok()) {
      for (const m of (await existingRes.json()).mappings || []) {
        await page.request.patch(
          `/api/questionnaires/${targetId}/mappings/${m.id}?workspace_id=${wsId}`,
          { data: { status: 'suggested' } }
        )
      }
    }

    // Navigate directly to mappings page
    await page.goto(`/dashboard/questionnaires/${targetId}/mappings`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Policy gap mapping' })).toBeVisible({ timeout: 15000 })

    // --- Generate gap mappings ---
    const generateBtn = page.getByRole('button', { name: /generate gap mappings|regenerate all/i }).first()
    await expect(generateBtn).toBeVisible({ timeout: 5000 })
    await generateBtn.click()

    // Wait for cards to render
    const approveButtons = page.getByRole('button', { name: 'Approve' })
    await expect(approveButtons.first()).toBeVisible({ timeout: 20000 })
    const total = await approveButtons.count()
    expect(total).toBeGreaterThanOrEqual(3)

    // Stats visible
    await expect(page.getByText('Total Qs', { exact: true })).toBeVisible()
    await expect(page.getByText('Mapped', { exact: true })).toBeVisible()

    // --- Approve Row 1 (first Approve button = first card) ---
    await approveButtons.first().click()
    await page.waitForTimeout(1500)
    await expect(page.locator('span').filter({ hasText: /^approved$/ }).first()).toBeVisible({ timeout: 5000 })

    // After approving Row 1: Row 1 has no Approve but still has Reject.
    // Reject buttons: [Row1, Row2, Row3, ...]
    // We want to reject Row 2 → use nth(1)
    const rejectButtons = page.getByRole('button', { name: 'Reject' })
    expect(await rejectButtons.count()).toBeGreaterThanOrEqual(2)
    await rejectButtons.nth(1).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('span').filter({ hasText: /^rejected$/ }).first()).toBeVisible({ timeout: 5000 })

    // Edit Row 3: Edit buttons are [Row1, Row2, Row3, ...]
    // Use nth(2) to target Row 3
    const editButtons = page.getByRole('button', { name: 'Edit' })
    expect(await editButtons.count()).toBeGreaterThanOrEqual(3)
    await editButtons.nth(2).click()
    const controlSelect = page.getByRole('combobox')
    await expect(controlSelect).toBeVisible({ timeout: 3000 })
    const optionCount = await controlSelect.locator('option').count()
    if (optionCount > 1) {
      await controlSelect.selectOption({ index: 1 })
    }
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('span').filter({ hasText: /^manual$/ }).first()).toBeVisible({ timeout: 5000 })

    // Regenerate: target a "suggested" row (Row 4+ if it exists, else any available)
    const regenButtons = page.getByRole('button', { name: 'Regenerate' })
    expect(await regenButtons.count()).toBeGreaterThan(0)
    await regenButtons.last().click()
    await page.waitForTimeout(2000)

    // --- Refresh and verify persistence ---
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Policy gap mapping' })).toBeVisible({ timeout: 15000 })

    // Approved badge must survive reload
    await expect(page.locator('span').filter({ hasText: /^approved$/ }).first()).toBeVisible({ timeout: 10000 })

    // Page still functional after reload
    await expect(page.getByRole('button', { name: /approve|reject|edit|regenerate/i }).first()).toBeVisible({ timeout: 10000 })
  })
})
