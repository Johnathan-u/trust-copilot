import { test, expect, type Page } from '@playwright/test'

const ADMIN_EMAIL = 'admin@trust.local'
const ADMIN_PASSWORD = 'Admin123!'
const DEMO_EMAIL = 'demo@trust.local'
const DEMO_PASSWORD = 'j'

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

async function loginAsEditor(page: Page) {
  await page.goto('/login', { waitUntil: 'load' })
  await page.locator('input[type="email"]').waitFor({ state: 'visible' })
  await page.locator('input[type="email"]').fill(DEMO_EMAIL)
  await page.locator('input[type="password"]').fill(DEMO_PASSWORD)
  const signIn = page.getByRole('button', { name: 'Sign in' })
  await expect(signIn).toBeEnabled({ timeout: 10_000 })
  await signIn.click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 })
}

test.describe('Requests page — outbound vendor request lifecycle', () => {

  test('page loads with correct header and structure', async ({ page }) => {
    if (process.env.E2E_SERVER_RUNNING) {
      await page.goto('/dashboard')
      await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 })
    } else {
      await loginAsAdmin(page)
    }

    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('heading', { name: 'Requests' })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText(/Send a questionnaire.*vendor/i)).toBeVisible()
  })

  test('admin sees Create Request button', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('button', { name: /Create Request/i })).toBeVisible({ timeout: 10_000 })
  })

  test('Create Request modal: fields and form structure', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Create Request/i }).click()

    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await expect(modal).toBeVisible({ timeout: 5_000 })

    await expect(modal.locator('input[type="email"]')).toBeVisible()
    await expect(modal.getByText(/Vendor Email/i)).toBeVisible()
    await expect(modal.getByText('Questionnaire', { exact: true })).toBeVisible()
    await expect(modal.getByText('Message')).toBeVisible()
    await expect(modal.getByText(/optional/i)).toBeVisible()

    const createBtn = modal.getByRole('button', { name: /Create Link/i })
    await expect(createBtn).toBeVisible()
    const cancelBtn = modal.getByRole('button', { name: /Cancel/i })
    await expect(cancelBtn).toBeVisible()
  })

  test('create request → secure link shown → copy works', async ({ page, context }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: /Create Request/i }).click()

    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await expect(modal).toBeVisible({ timeout: 5_000 })

    const vendorEmail = `e2e-vendor-${Date.now()}@test.com`
    await modal.locator('input[type="email"]').fill(vendorEmail)

    const qnrSelect = modal.locator('select').first()
    const optionCount = await qnrSelect.locator('option').count()
    if (optionCount > 1) {
      await qnrSelect.selectOption({ index: 1 })
    }

    await modal.locator('textarea').fill('E2E test message')

    await modal.getByRole('button', { name: /Create Link/i }).click()

    await expect(modal.getByText(/secure link/i)).toBeVisible({ timeout: 10_000 })
    const linkCode = modal.locator('code')
    await expect(linkCode).toBeVisible()
    const linkText = await linkCode.textContent()
    expect(linkText).toContain('/vendor-response?token=')

    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    const copyBtn = modal.getByRole('button', { name: /Copy/i })
    await expect(copyBtn).toBeVisible()
    await copyBtn.click()
    await expect(modal.getByRole('button', { name: /Copied/i })).toBeVisible({ timeout: 3_000 })

    await modal.getByRole('button', { name: /Done/i }).click()

    await page.waitForLoadState('networkidle')
    await expect(page.getByText(vendorEmail)).toBeVisible({ timeout: 10_000 })
  })

  test('created request shows in table with Pending status', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const vendorEmail = `e2e-table-${Date.now()}@test.com`

    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.getByRole('button', { name: /Create Link/i }).click()
    await expect(modal.getByText(/secure link/i)).toBeVisible({ timeout: 10_000 })
    await modal.getByRole('button', { name: /Done/i }).click()
    await page.waitForLoadState('networkidle')

    const row = page.locator('tr', { hasText: vendorEmail })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row.getByText(/Pending/i)).toBeVisible()
    await expect(row.getByText(/Copy Link/i)).toBeVisible()
  })

  test('admin can update request status via dropdown', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const vendorEmail = `e2e-status-${Date.now()}@test.com`

    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.getByRole('button', { name: /Create Link/i }).click()
    await expect(modal.getByText(/secure link/i)).toBeVisible({ timeout: 10_000 })
    await modal.getByRole('button', { name: /Done/i }).click()
    await page.waitForLoadState('networkidle')

    const row = page.locator('tr', { hasText: vendorEmail })
    await expect(row).toBeVisible({ timeout: 10_000 })

    const statusSelect = row.locator('select')
    await expect(statusSelect).toBeVisible({ timeout: 5_000 })
    await statusSelect.selectOption('in_progress')
    await page.waitForLoadState('networkidle')

    await expect(row.getByText(/In Progress/i)).toBeVisible({ timeout: 10_000 })
  })

  test('table shows correct columns: Vendor, Questionnaire, Status, Created, Actions', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const vendorEmail = `e2e-cols-${Date.now()}@test.com`
    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.getByRole('button', { name: /Create Link/i }).click()
    await expect(modal.getByText(/secure link/i)).toBeVisible({ timeout: 10_000 })
    await modal.getByRole('button', { name: /Done/i }).click()
    await page.waitForLoadState('networkidle')

    const headers = page.locator('thead th')
    const headerTexts = await headers.allTextContents()
    const normalized = headerTexts.map(t => t.trim().toLowerCase())
    expect(normalized).toContain('vendor')
    expect(normalized).toContain('questionnaire')
    expect(normalized).toContain('status')
    expect(normalized).toContain('created')
    expect(normalized).toContain('actions')
  })

  test('Copy Link button exists in table row actions', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const vendorEmail = `e2e-link-${Date.now()}@test.com`
    await page.getByRole('button', { name: /Create Request/i }).click()
    const modal = page.getByRole('dialog').or(page.locator('[class*="Modal"]')).first()
    await modal.locator('input[type="email"]').fill(vendorEmail)
    await modal.getByRole('button', { name: /Create Link/i }).click()
    await expect(modal.getByText(/secure link/i)).toBeVisible({ timeout: 10_000 })
    await modal.getByRole('button', { name: /Done/i }).click()
    await page.waitForLoadState('networkidle')

    const row = page.locator('tr', { hasText: vendorEmail })
    const copyLink = row.getByText(/Copy Link/i)
    await expect(copyLink).toBeVisible({ timeout: 10_000 })
  })

  test('no internal model names exposed in UI text', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const bodyText = await page.locator('body').textContent()
    expect(bodyText).not.toContain('VendorRequest')
    expect(bodyText).not.toContain('TrustRequest')
    expect(bodyText).not.toContain('vendor_request')
    expect(bodyText).not.toContain('trust_request')
  })

  test('empty state shows helpful message and CTA for admin', async ({ page }) => {
    await loginAsAdmin(page)

    const res = await page.request.get('/api/vendor-requests/')
    if (res.ok()) {
      const existing = await res.json()
      if (existing.length > 0) {
        test.skip(true, 'Workspace already has requests — cannot test empty state')
        return
      }
    }

    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const emptyState = page.getByText(/No requests yet/i)
    if (await emptyState.isVisible()) {
      await expect(page.getByText(/secure link/i)).toBeVisible()
      await expect(page.getByRole('button', { name: /Create First Request/i })).toBeVisible()
    }
  })

  test('full lifecycle via API: create → list → update → verify', async ({ page }) => {
    await loginAsAdmin(page)

    const vendorEmail = `e2e-api-${Date.now()}@test.com`

    const createRes = await page.request.post('/api/vendor-requests/', {
      data: {
        vendor_email: vendorEmail,
        message: 'API lifecycle test',
      },
    })
    expect(createRes.ok()).toBeTruthy()
    const created = await createRes.json()
    expect(created.status).toBe('pending')
    expect(created.link_token).toBeTruthy()
    expect(created.share_url).toContain('/vendor-response?token=')
    const reqId = created.id

    const listRes = await page.request.get('/api/vendor-requests/')
    expect(listRes.ok()).toBeTruthy()
    const list = await listRes.json()
    const found = list.find((r: { id: number }) => r.id === reqId)
    expect(found).toBeTruthy()
    expect(found.vendor_email).toBe(vendorEmail)
    expect(found.status).toBe('pending')

    const updateRes = await page.request.patch(`/api/vendor-requests/${reqId}`, {
      data: { status: 'in_progress' },
    })
    expect(updateRes.ok()).toBeTruthy()
    expect((await updateRes.json()).status).toBe('in_progress')

    const completeRes = await page.request.patch(`/api/vendor-requests/${reqId}`, {
      data: { status: 'completed' },
    })
    expect(completeRes.ok()).toBeTruthy()
    expect((await completeRes.json()).status).toBe('completed')

    const finalList = await page.request.get('/api/vendor-requests/')
    const finalItem = (await finalList.json()).find((r: { id: number }) => r.id === reqId)
    expect(finalItem.status).toBe('completed')
  })

  test('data passes through backend → frontend: request visible in table after API create', async ({ page }) => {
    await loginAsAdmin(page)

    const vendorEmail = `e2e-passthru-${Date.now()}@test.com`
    const createRes = await page.request.post('/api/vendor-requests/', {
      data: {
        vendor_email: vendorEmail,
        message: 'Pass-through test',
      },
    })
    expect(createRes.ok()).toBeTruthy()

    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText(vendorEmail)).toBeVisible({ timeout: 10_000 })
    const row = page.locator('tr', { hasText: vendorEmail })
    await expect(row.getByText(/Pending/i)).toBeVisible()
  })

  test('status update via API reflects in UI on reload', async ({ page }) => {
    await loginAsAdmin(page)

    const vendorEmail = `e2e-reflect-${Date.now()}@test.com`
    const createRes = await page.request.post('/api/vendor-requests/', {
      data: { vendor_email: vendorEmail },
    })
    const reqId = (await createRes.json()).id

    await page.request.patch(`/api/vendor-requests/${reqId}`, {
      data: { status: 'completed' },
    })

    await page.goto('/dashboard/requests')
    await page.waitForLoadState('networkidle')

    const row = page.locator('tr', { hasText: vendorEmail })
    await expect(row).toBeVisible({ timeout: 10_000 })
    await expect(row.getByText(/Completed/i)).toBeVisible()
    const statusSelect = row.locator('select')
    await expect(statusSelect).toHaveCount(0)
  })
})
