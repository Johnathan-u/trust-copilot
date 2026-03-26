import { test, expect, type Page } from '@playwright/test'

const ADMIN_EMAIL = 'admin@trust.local'
const ADMIN_PASSWORD = 'Admin123!'

async function loginAsAdmin(page: Page) {
  await page.goto('/login', { waitUntil: 'load' })
  await page.locator('input[type="email"]').waitFor({ state: 'visible' })
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL)
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD)
  const signIn = page.getByRole('button', { name: 'Sign in' })
  await expect(signIn).toBeEnabled({ timeout: 10_000 })
  await signIn.click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 })
}

async function createRequestViaAPI(page: Page, email?: string, message?: string): Promise<{ link_token: string; share_url: string }> {
  const res = await page.request.post('/api/vendor-requests/', {
    data: {
      vendor_email: email ?? `e2e-vr-${Date.now()}@test.com`,
      message: message ?? 'E2E vendor response test',
    },
  })
  expect(res.ok()).toBeTruthy()
  const data = await res.json()
  return { link_token: data.link_token, share_url: data.share_url }
}

test.describe('Vendor Response landing page — public, unauthenticated', () => {

  test('invalid token shows error state', async ({ page }) => {
    await page.goto('/vendor-response?token=this-token-does-not-exist-at-all')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/invalid|expired/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/Link Not Found/i)).toBeVisible()
    await expect(page.getByText(/contact.*person.*sent/i)).toBeVisible()
  })

  test('missing token shows error state', async ({ page }) => {
    await page.goto('/vendor-response')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/no token|invalid|check your link/i)).toBeVisible({ timeout: 10_000 })
  })

  test('valid token loads request details', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page, undefined, 'Please review our security controls.')

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/Vendor Request/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/security questionnaire/i)).toBeVisible()
    await expect(page.getByText('Please review our security controls.')).toBeVisible()
    await expect(page.getByText(/Pending/i)).toBeVisible()
  })

  test('page shows Trust Copilot branding', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Trust Copilot')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('TC')).toBeVisible()
  })

  test('no internal model names on page', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Vendor Request/i)).toBeVisible({ timeout: 10_000 })

    const bodyText = await page.locator('body').textContent()
    expect(bodyText).not.toContain('VendorRequest')
    expect(bodyText).not.toContain('TrustRequest')
    expect(bodyText).not.toContain('workspace_id')
    expect(bodyText).not.toContain('link_token')
  })

  test('secure link warning shown', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/secure link.*do not share/i)).toBeVisible({ timeout: 10_000 })
  })

  test('request without questionnaire shows no-questionnaire message', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/no questionnaire.*attached/i)).toBeVisible({ timeout: 10_000 })
  })

  test('completed request shows completion state', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    const listRes = await page.request.get('/api/vendor-requests/')
    const items = await listRes.json()
    const match = items.find((i: { link_token: string }) => i.link_token === link_token)
    expect(match).toBeTruthy()

    await page.request.patch(`/api/vendor-requests/${match.id}`, {
      data: { status: 'completed' },
    })

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/already been completed/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/no further action/i)).toBeVisible()
  })

  test('status update from admin reflects on vendor page', async ({ page }) => {
    await loginAsAdmin(page)
    const { link_token } = await createRequestViaAPI(page)

    await page.goto(`/vendor-response?token=${link_token}`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/Pending/i)).toBeVisible({ timeout: 10_000 })

    const listRes = await page.request.get('/api/vendor-requests/')
    const match = (await listRes.json()).find((i: { link_token: string }) => i.link_token === link_token)
    await page.request.patch(`/api/vendor-requests/${match.id}`, {
      data: { status: 'in_progress' },
    })

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(/In Progress/i)).toBeVisible({ timeout: 10_000 })
  })

  test('end-to-end: create on dashboard → open vendor link → see details', async ({ page }) => {
    await loginAsAdmin(page)

    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await expect(modal).toBeVisible({ timeout: 5_000 })

    const vendorEmail = `e2e-full-${Date.now()}@vendor.com`
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.locator('textarea').fill('Full end-to-end test message')
    await modal.getByRole('button', { name: /Create Link/i }).click()

    const linkCode = modal.locator('code')
    await expect(linkCode).toBeVisible({ timeout: 10_000 })
    const fullUrl = await linkCode.textContent()
    expect(fullUrl).toContain('/vendor-response?token=')

    await modal.getByRole('button', { name: /Done/i }).click()

    const tokenMatch = fullUrl?.match(/token=([^&]+)/)
    expect(tokenMatch).toBeTruthy()
    const token = tokenMatch![1]

    await page.goto(`/vendor-response?token=${token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/Vendor Request/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Full end-to-end test message')).toBeVisible()
    await expect(page.getByText(/Pending/i)).toBeVisible()
  })

  test('integrated flow: dashboard create → vendor page → status transitions → vendor page reflects all states', async ({ page }) => {
    await loginAsAdmin(page)

    // ── Step 1: Create request on dashboard UI ──────────────────────────
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await expect(modal).toBeVisible({ timeout: 5_000 })

    const vendorEmail = `e2e-integrated-${Date.now()}@vendor.com`
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.locator('textarea').fill('Integrated flow test')
    await modal.getByRole('button', { name: /Create Link/i }).click()

    // ── Step 2: Extract token from success modal ────────────────────────
    const linkCode = modal.locator('code')
    await expect(linkCode).toBeVisible({ timeout: 10_000 })
    const fullUrl = await linkCode.textContent()
    expect(fullUrl).toContain('/vendor-response?token=')
    const token = fullUrl!.match(/token=([^&]+)/)![1]

    await modal.getByRole('button', { name: /Done/i }).click()
    await page.waitForLoadState('networkidle')

    // Confirm row appeared in dashboard table
    const row = page.locator('tr', { hasText: vendorEmail })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row.getByText(/Pending/i)).toBeVisible()

    // ── Step 3: Vendor page — verify Pending state ──────────────────────
    await page.goto(`/vendor-response?token=${token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/Vendor Request/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Integrated flow test')).toBeVisible()
    await expect(page.getByText(/Pending/i)).toBeVisible()
    // No internal names leaked
    const bodyPending = await page.locator('body').textContent()
    expect(bodyPending).not.toContain('VendorRequest')
    expect(bodyPending).not.toContain('workspace_id')

    // ── Step 4: Admin updates status → In Progress on dashboard ─────────
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const rowAfter = page.locator('tr', { hasText: vendorEmail })
    await expect(rowAfter).toBeVisible({ timeout: 10_000 })
    const statusSelect = rowAfter.locator('select')
    await expect(statusSelect).toBeVisible({ timeout: 5_000 })
    await statusSelect.selectOption('in_progress')
    await page.waitForLoadState('networkidle')
    await expect(rowAfter.getByText(/In Progress/i)).toBeVisible({ timeout: 10_000 })

    // ── Step 5: Vendor page — verify In Progress state ──────────────────
    await page.goto(`/vendor-response?token=${token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/In Progress/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('Integrated flow test')).toBeVisible()

    // ── Step 6: Admin updates status → Completed on dashboard ───────────
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const rowFinal = page.locator('tr', { hasText: vendorEmail })
    await expect(rowFinal).toBeVisible({ timeout: 10_000 })
    const finalSelect = rowFinal.locator('select')
    await expect(finalSelect).toBeVisible({ timeout: 5_000 })
    await finalSelect.selectOption('completed')
    await page.waitForLoadState('networkidle')
    await expect(rowFinal.getByText(/Completed/i)).toBeVisible({ timeout: 10_000 })
    // Completed rows should not have a status dropdown
    await expect(rowFinal.locator('select')).toHaveCount(0)

    // ── Step 7: Vendor page — verify Completed state ────────────────────
    await page.goto(`/vendor-response?token=${token}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(/already been completed/i)).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/no further action/i)).toBeVisible()
    // Message should NOT be shown on completed page (clean terminal state)
    await expect(page.getByText('Integrated flow test')).not.toBeVisible()
  })
})
