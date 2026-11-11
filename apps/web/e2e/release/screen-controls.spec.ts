import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const control = {
  id: 41,
  workspace_id: 7,
  framework_control_id: null,
  control_key: null,
  framework: null,
  category: null,
  name: 'Access review',
  custom_name: 'Access review',
  status: 'verified',
  owner_user_id: 42,
  owner_team: 'Security',
  last_reviewed_at: null,
  verified_at: null,
  verified_by_user_id: null,
  created_at: '2026-10-01T09:00:00Z',
  updated_at: '2026-10-01T09:00:00Z',
  evidence_count: 1,
  max_confidence: 0.9,
  has_verified: true,
  canonical: {
    contract_version: 'control-contract/v1',
    id: 'custom:access-review',
    version: null,
    content_version: null,
    owner_user_id: 42,
    owner_team: 'Security',
    lifecycle: 'verified',
    status_aligned: true,
    evidence: {
      contract_version: 'control-evidence/v1',
      workspace_scoped: true,
      exactly_one_target: true,
      legacy_count: 1,
      canonical_count: 1,
      mirrored: true,
    },
  },
}

const blockedFramework = {
  id: null,
  name: 'SOC 2',
  version: null,
  created_at: null,
  catalog_key: 'soc2',
  source_provenance: {},
  rights_status: 'blocked_pending_rights',
  licence_status: 'blocked_pending_rights',
  enablement_state: 'blocked',
  catalog_kind: 'advertised',
  production_catalog: false,
  contract_version: 'framework-catalog/v1',
  content_version: null,
  content_origin: null,
  blocked_reason: 'Rights review pending.',
  synthetic_dev_content_present: false,
  dev_test_only: false,
  stored_control_count: 0,
  controls_are_production_catalog: false,
}

const licensedFramework = {
  ...blockedFramework,
  rights_status: 'cleared',
  licence_status: 'cleared',
  production_catalog: true,
  enablement_state: 'available',
  content_version: '2026.1',
  blocked_reason: null,
}

const enabledFramework = {
  ...licensedFramework,
  id: 9,
  enablement_state: 'enabled',
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installApi(
  page: Page,
  role = 'admin',
  options: { extraWorkspace?: boolean; frameworks?: unknown } = {}
) {
  const canAdmin = role === 'admin' || role === 'owner'
  const canReview = role !== 'viewer'
  await page.context().addCookies([
    {
      name: 'tc_session',
      value: 'synthetic-session',
      domain: '127.0.0.1',
      path: '/',
    },
  ])
  await page.route('**/api/**', async (route) => {
    const p = new URL(route.request().url()).pathname
    if (p === '/api/auth/me')
      return json(route, {
        id: 42,
        email: 'reviewer@example.com',
        display_name: 'Avery Reviewer',
        workspace_id: 7,
        workspace_name: 'Synthetic workspace',
        workspace_slug: 'synthetic',
        role,
        workspaces: [
          { id: 7, name: 'Synthetic workspace', slug: 'synthetic', role },
          ...(options.extraWorkspace
            ? [{ id: 8, name: 'Second workspace', slug: 'second', role }]
            : []),
        ],
        permissions: {
          can_admin: canAdmin,
          can_review: canReview,
          can_edit: canAdmin || role === 'editor',
          can_export: canAdmin,
        },
        needs_onboarding: false,
        subscription: { status: 'trialing', plan: 'synthetic' },
        mfa_enrolled: true,
        mfa_required_for_workspace: false,
        workspace_auth_policy: {
          mfa_required: false,
          session_max_age_seconds: null,
        },
      })
    if (p === '/api/compliance/controls') return json(route, [control])
    if (p === '/api/compliance/controls/41') return json(route, control)
    if (p === '/api/compliance/controls/41/evidence')
      return json(route, [
        {
          id: 61,
          control_id: 41,
          evidence_id: 91,
          confidence_score: 0.9,
          verified: true,
          last_verified_at: '2026-10-01T09:00:00Z',
          created_at: '2026-10-01T09:00:00Z',
          stale: true,
          expired: true,
          canonical: {
            contract_version: 'control-evidence/v1',
            target_kind: 'evidence_item',
            workspace_scoped: true,
            exactly_one_target: true,
            evidence_item_id: 91,
          },
          evidence: {
            id: 91,
            workspace_id: 7,
            document_id: null,
            source_type: 'manual',
            title: 'Access review record',
            created_at: '2026-10-01T09:00:00Z',
            tags: [],
          },
        },
      ])
    if (p === '/api/compliance-coverage')
      return json(route, {
        kpi: {},
        framework_coverage: [],
        blind_spots: [],
        weak_areas: [],
        evidence_strength: [],
        recommended_evidence: [],
        trends: [],
        drill_down: [],
        control_coverage: {
          schema_version: 'compliance-coverage-controls/v1',
          numerator: 0,
          denominator: 1,
          coverage_pct: 0,
          qualified_control_ids: [],
          explanations: [
            {
              control_id: 41,
              state: 'stale',
              rule: 'expired',
              effect: 'excluded_from_numerator',
              denominator_changed: false,
              framework_id: null,
            },
          ],
        },
      })
    if (p === '/api/auth/switch-workspace') {
      const body = route.request().postDataJSON() as { workspace_id?: number }
      const id = body.workspace_id
      if (id !== 7 && id !== 8) return json(route, { detail: 'Unknown' }, 404)
      return json(route, {
        workspace_id: id,
        workspace_name: id === 8 ? 'Second workspace' : 'Synthetic workspace',
        workspace_slug: id === 8 ? 'second' : 'synthetic',
        role,
      })
    }
    if (p === '/api/compliance/frameworks')
      return json(route, options.frameworks ?? [blockedFramework])
    if (p === '/api/members')
      return json(route, {
        members: [
          {
            id: 10,
            user_id: 42,
            email: 'reviewer@example.com',
            display_name: 'Avery Reviewer',
            role: 'admin',
            suspended: false,
            created_at: null,
          },
          {
            id: 11,
            user_id: 43,
            email: 'owner@example.com',
            display_name: 'Morgan Owner',
            role: 'editor',
            suspended: false,
            created_at: null,
          },
        ],
      })
    if (p.includes('unread-count')) return json(route, { count: 0 })
    if (p.includes('/auth/alerts')) return json(route, { alerts: [] })
    return json(route, {})
  })
}

async function acknowledgeControlPatch(page: Page) {
  await page.route('**/api/compliance/controls/41', async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    const body = route.request().postDataJSON() as {
      owner_team?: string
      owner_user_id?: number
      status?: string
    }
    return json(route, {
      ...control,
      owner_team: body.owner_team ?? control.owner_team,
      owner_user_id: body.owner_user_id ?? control.owner_user_id,
      status: body.status ?? control.status,
      canonical: {
        ...control.canonical,
        owner_team: body.owner_team ?? control.canonical.owner_team,
        owner_user_id: body.owner_user_id ?? control.canonical.owner_user_id,
        lifecycle: body.status ?? control.canonical.lifecycle,
      },
    })
  })
}

async function unloadBlocked(page: Page) {
  return page.evaluate(() => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event.defaultPrevented
  })
}

async function focusedLabel(page: Page) {
  return page.evaluate(() => {
    const el = document.activeElement
    if (!el || el === document.body) return 'body'
    const labelledby = el.getAttribute('aria-labelledby')
    if (labelledby) {
      const text = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent?.trim() ?? '')
        .filter(Boolean)
        .join(' ')
      if (text) return text
    }
    const aria = el.getAttribute('aria-label')
    if (aria) return aria
    if (
      el instanceof HTMLInputElement ||
      el instanceof HTMLSelectElement ||
      el instanceof HTMLTextAreaElement
    ) {
      const wrap = el.closest('label')
      if (wrap) {
        const copy = wrap.cloneNode(true) as HTMLElement
        copy
          .querySelectorAll('input,select,textarea')
          .forEach((node) => node.remove())
        const text = copy.textContent?.replace(/\s+/g, ' ').trim()
        if (text) return text
      }
    }
    return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80)
  })
}

/** The controlled select is reverted before Playwright can observe selectOption. */
async function chooseWorkspace(page: Page, id: string) {
  await page.locator('#sidebar-workspace-select').evaluate((node, value) => {
    const select = node as HTMLSelectElement
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  }, id)
}

async function routeFrameworkEnable(
  page: Page,
  enableBody: unknown,
  enableStatus = 200,
  options: { laterList?: unknown; hold?: Promise<void> } = {}
) {
  let posted = false
  await page.route('**/api/compliance/frameworks**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/enable')) {
      posted = true
      if (options.hold) await options.hold
      return json(route, enableBody, enableStatus)
    }
    return json(
      route,
      posted ? (options.laterList ?? [licensedFramework]) : [licensedFramework]
    )
  })
}

test('library and detail keep verified lifecycle separate from expired evidence', async ({
  page,
}) => {
  await installApi(page)
  await page.goto('/dashboard/controls')
  await expect(
    page.getByRole('heading', { name: 'Control library', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Pending content licensing', { exact: true })
  ).toBeVisible()
  const row = page.getByRole('row').filter({
    has: page.getByRole('link', { name: 'Access review', exact: true }),
  })
  await expect(row).toContainText('Verified')
  await expect(row).toContainText('Stale evidence')
  await row.getByRole('link', { name: 'Access review', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Access review', exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Backing evidence', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Stale evidence', { exact: true })).toBeVisible()
  await expect(page.locator('#main-content')).not.toContainText(
    'custom:access-review'
  )
})

for (const role of ['owner', 'admin', 'editor', 'reviewer', 'viewer']) {
  test(`${role} receives only granted control actions`, async ({ page }) => {
    await installApi(page, role)
    await page.goto('/dashboard/controls/41')
    if (role === 'viewer') {
      await expect(
        page.getByRole('heading', { name: 'This section is not available' })
      ).toBeVisible()
      await expect(
        page.getByText('Access review record', { exact: true })
      ).toHaveCount(0)
      return
    }
    await expect(
      page.getByRole('heading', { name: 'Access review', exact: true })
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: 'Mark unverified', exact: true })
    ).toBeVisible()
    await expect(page.getByLabel('Owner', { exact: true })).toHaveCount(
      ['owner', 'admin'].includes(role) ? 1 : 0
    )
    await expect(
      page.getByRole('button', { name: 'Save changes', exact: true })
    ).toHaveCount(['owner', 'admin'].includes(role) ? 1 : 0)
  })
}

test('save sends selected member, waits for acknowledgement and keeps rejected edits', async ({
  page,
}) => {
  await installApi(page)
  let release: () => void = () => {}
  const hold = new Promise<void>((resolve) => {
    release = resolve
  })
  let posted: unknown
  await page.route('**/api/compliance/controls/41', async (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback()
    posted = route.request().postDataJSON()
    await hold
    return json(
      route,
      { detail: 'Internal TC-SECRET-001 owner_user_id=43' },
      409
    )
  })
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner', { exact: true }).selectOption('43')
  await page.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Saving changes', exact: true })
  ).toBeDisabled()
  await expect(page.getByText('Changes saved', { exact: true })).toHaveCount(0)
  await expect.poll(() => posted).toEqual({ owner_user_id: 43 })
  release()
  await expect(page.locator('#main-content').getByRole('alert')).toContainText(
    'Changes could not be saved'
  )
  await expect(page.getByLabel('Owner', { exact: true })).toHaveValue('43')
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await expect(page.locator('#main-content')).not.toContainText('TC-SECRET')
  await page.unroute('**/api/compliance/controls/41')
  await page.route('**/api/compliance/controls/41', async (route) => {
    if (route.request().method() === 'PATCH')
      return json(route, {
        ...control,
        owner_user_id: 43,
        canonical: { ...control.canonical, owner_user_id: 43 },
      })
    return json(route, control)
  })
  await page.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(page.getByText('Changes saved', { exact: true })).toBeVisible()
  await expect(page.getByText('Unsaved changes', { exact: true })).toHaveCount(
    0
  )
})

test('unsaved edits require confirmation before leaving detail', async ({
  page,
}) => {
  await installApi(page)
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner team').fill('New team')
  await page.getByRole('link', { name: 'Back to control library' }).click()
  const dialog = page.getByRole('alertdialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Owner team')).toHaveValue('New team')
  await page.getByRole('link', { name: 'Back to control library' }).click()
  await dialog
    .getByRole('button', { name: 'Discard changes', exact: true })
    .click()
  await expect(page).toHaveURL(/\/dashboard\/controls$/)
})

for (const role of ['owner', 'admin', 'editor', 'reviewer', 'viewer']) {
  test(`${role} enablement on the library follows the admin grant`, async ({
    page,
  }) => {
    await installApi(page, role, { frameworks: [licensedFramework] })
    await page.goto('/dashboard/controls')
    const enable = page.getByRole('button', {
      name: 'Enable framework',
      exact: true,
    })
    if (role === 'viewer') {
      await expect(
        page.getByRole('heading', { name: 'This section is not available' })
      ).toBeVisible()
      await expect(
        page.getByRole('heading', { name: 'Control library', exact: true })
      ).toHaveCount(0)
      await expect(enable).toHaveCount(0)
      return
    }
    await expect(
      page.getByRole('heading', { name: 'Control library', exact: true })
    ).toBeVisible()
    await expect(
      page.getByText('Licensed content available', { exact: true })
    ).toBeVisible()
    await expect(enable).toHaveCount(
      role === 'admin' || role === 'owner' ? 1 : 0
    )
  })
}

test('Framework enabled appears only after an acknowledging enable response', async ({
  page,
}) => {
  let release = () => {}
  const hold = new Promise<void>((resolve) => {
    release = resolve
  })
  let posted: unknown
  await installApi(page, 'admin', { frameworks: [licensedFramework] })
  await page.route('**/api/compliance/frameworks**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/enable')) {
      posted = route.request().postDataJSON()
      await hold
      return json(route, enabledFramework)
    }
    return json(route, [licensedFramework])
  })
  await page.goto('/dashboard/controls')
  await page
    .getByRole('button', { name: 'Enable framework', exact: true })
    .click()
  await expect(
    page.getByRole('button', { name: 'Activating…', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Framework enabled', { exact: true })
  ).toHaveCount(0)
  expect(posted).toEqual({ catalog_key: 'soc2' })
  release()
  await expect(
    page.getByText('Framework enabled', { exact: true })
  ).toBeVisible()
  await expect(page.getByText('Enabled', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Enable framework', exact: true })
  ).toHaveCount(0)
})

test('an enable body that is not a production catalog shows no success', async ({
  page,
}) => {
  await installApi(page, 'admin', { frameworks: [licensedFramework] })
  await routeFrameworkEnable(page, licensedFramework, 200, {
    laterList: [enabledFramework],
  })
  await page.goto('/dashboard/controls')
  await page
    .getByRole('button', { name: 'Enable framework', exact: true })
    .click()
  await expect(
    page.getByText('Framework activation could not be confirmed')
  ).toBeVisible()
  await expect(
    page.getByText('Framework enabled', { exact: true })
  ).toHaveCount(0)
  await expect(
    page.getByRole('button', { name: 'Enable framework', exact: true })
  ).toBeVisible()
})

test('a malformed enable success shows no success', async ({ page }) => {
  await installApi(page, 'admin', { frameworks: [licensedFramework] })
  await routeFrameworkEnable(page, { ok: true }, 200, {
    laterList: [enabledFramework],
  })
  await page.goto('/dashboard/controls')
  await page
    .getByRole('button', { name: 'Enable framework', exact: true })
    .click()
  await expect(
    page.getByText('Framework activation could not be confirmed')
  ).toBeVisible()
  await expect(
    page.getByText('Framework enabled', { exact: true })
  ).toHaveCount(0)
  await expect(page.getByText('ok', { exact: true })).toHaveCount(0)
})

for (const status of [403, 409, 500]) {
  test(`enable ${status} shows no success`, async ({ page }) => {
    await installApi(page, 'admin', { frameworks: [licensedFramework] })
    await routeFrameworkEnable(
      page,
      { detail: 'secret-enable-failure' },
      status,
      { laterList: [enabledFramework] }
    )
    await page.goto('/dashboard/controls')
    await page
      .getByRole('button', { name: 'Enable framework', exact: true })
      .click()
    await expect(
      page.getByText('Framework activation could not be confirmed')
    ).toBeVisible()
    await expect(
      page.getByText('Framework enabled', { exact: true })
    ).toHaveCount(0)
    await expect(page.locator('#main-content')).not.toContainText(
      'secret-enable-failure'
    )
    await expect(
      page.getByRole('button', { name: 'Enable framework', exact: true })
    ).toBeVisible()
  })
}

test('cancelling a workspace switch keeps unsaved control edits', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installApi(page, 'admin', { extraWorkspace: true })
  let switches = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/auth/switch-workspace')
      switches += 1
  })
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner team').fill('Kept team')
  await expect.poll(() => unloadBlocked(page)).toBe(true)
  await chooseWorkspace(page, '8')
  const dialog = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Cancel', exact: true })
  ).toBeFocused()
  expect(switches).toBe(0)
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel('Owner team')).toHaveValue('Kept team')
  await expect(page.getByLabel('Workspace', { exact: true })).toHaveValue('7')
  await expect(page).toHaveURL(/\/dashboard\/controls\/41$/)
  await expect.poll(() => unloadBlocked(page)).toBe(true)
  expect(switches).toBe(0)
})

test('confirming a workspace switch discards unsaved control edits', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installApi(page, 'admin', { extraWorkspace: true })
  let switches = 0
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/auth/switch-workspace')
      switches += 1
  })
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner team').fill('Kept team')
  await chooseWorkspace(page, '8')
  const dialog = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await dialog
    .getByRole('button', { name: 'Discard changes', exact: true })
    .click()
  await expect(page.getByLabel('Workspace', { exact: true })).toHaveValue('8')
  await expect(page.getByLabel('Owner team')).toHaveValue('Security')
  await expect(page).toHaveURL(/\/dashboard\/controls\/41$/)
  await expect.poll(() => unloadBlocked(page)).toBe(false)
  expect(switches).toBe(1)
})

test('cancelling client-side Back keeps unsaved control edits', async ({
  page,
}) => {
  await installApi(page)
  await page.goto('/dashboard/controls')
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner team').fill('Kept team')
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await page.evaluate(() => history.back())
  const dialog = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await expect(dialog).toBeVisible()
  await expect(
    dialog.getByRole('button', { name: 'Cancel', exact: true })
  ).toBeFocused()
  await expect(page).toHaveURL(/\/dashboard\/controls\/41$/)
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Owner team')).toHaveValue('Kept team')
  await expect(page).toHaveURL(/\/dashboard\/controls\/41$/)
  await expect.poll(() => unloadBlocked(page)).toBe(true)
})

test('confirming client-side Back discards unsaved control edits', async ({
  page,
}) => {
  await installApi(page)
  await page.goto('/dashboard/controls')
  await page.goto('/dashboard/controls/41')
  await page.getByLabel('Owner team').fill('Kept team')
  await expect(page.getByText('Unsaved changes', { exact: true })).toBeVisible()
  await page.evaluate(() => history.back())
  const dialog = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await dialog
    .getByRole('button', { name: 'Discard changes', exact: true })
    .click()
  await expect(page).toHaveURL(/\/dashboard\/controls$/)
  await expect(
    page.getByRole('heading', { name: 'Control library', exact: true })
  ).toBeVisible()
  await expect(page.getByLabel('Owner team')).toHaveCount(0)
})

test('beforeunload is set while control edits are dirty and cleared after save or discard', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installApi(page, 'admin', { extraWorkspace: true })
  await acknowledgeControlPatch(page)
  await page.goto('/dashboard/controls/41')
  await expect.poll(() => unloadBlocked(page)).toBe(false)
  await page.getByLabel('Owner team').fill('Kept team')
  await expect.poll(() => unloadBlocked(page)).toBe(true)
  await chooseWorkspace(page, '8')
  const dialog = page.getByRole('alertdialog', {
    name: 'Discard unsaved changes?',
  })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Owner team')).toHaveValue('Kept team')
  await expect.poll(() => unloadBlocked(page)).toBe(true)
  await page.getByRole('button', { name: 'Save changes', exact: true }).click()
  await expect(page.getByText('Changes saved', { exact: true })).toBeVisible()
  await expect.poll(() => unloadBlocked(page)).toBe(false)
  await page.getByLabel('Owner team').fill('Discard me')
  await expect.poll(() => unloadBlocked(page)).toBe(true)
  await page.getByRole('button', { name: 'Reset changes', exact: true }).click()
  await expect(page.getByLabel('Owner team')).toHaveValue('Kept team')
  await expect.poll(() => unloadBlocked(page)).toBe(false)
})

test('failed evidence verification stays unconfirmed and does not change lifecycle', async ({
  page,
}) => {
  await installApi(page)
  await page.route('**/api/compliance/controls/41/evidence/61', (route) =>
    json(route, { detail: 'Private evidence details' }, 403)
  )
  await page.goto('/dashboard/controls/41')
  await page
    .getByRole('button', { name: 'Mark unverified', exact: true })
    .click()
  await expect(page.locator('#main-content').getByRole('alert')).toContainText(
    'Evidence review could not be saved'
  )
  await expect(
    page.getByRole('button', { name: 'Mark unverified', exact: true })
  ).toBeEnabled()
  await expect(page.getByLabel('Lifecycle', { exact: true })).toHaveValue(
    'verified'
  )
  await expect(page.locator('#main-content')).not.toContainText(
    'Private evidence details'
  )
})

for (const status of [403, 404, 500]) {
  test(`control detail handles ${status} without exposing a row`, async ({
    page,
  }) => {
    await installApi(page)
    await page.route('**/api/compliance/controls/41', (route) =>
      json(route, { detail: 'foreign workspace 999' }, status)
    )
    await page.goto('/dashboard/controls/41')
    await expect(page.locator('[data-state="error"]')).toBeVisible()
    await expect(
      page.getByText('Access review record', { exact: true })
    ).toHaveCount(0)
    await expect(page.locator('#main-content')).not.toContainText('999')
  })
}

test('list load recovers from error and malformed data is not an empty success', async ({
  page,
}) => {
  await installApi(page)
  let response: unknown = { items: [] }
  let status = 200
  await page.route('**/api/compliance/controls', (route) =>
    json(route, response, status)
  )
  await page.goto('/dashboard/controls')
  await expect(page.locator('[data-state="error"]')).toBeVisible()
  await expect(page.getByText('No controls yet', { exact: true })).toHaveCount(
    0
  )
  status = 500
  await page
    .locator('[data-state="error"]')
    .getByRole('button', { name: 'Try again' })
    .click()
  await expect(
    page.getByRole('heading', { name: 'Something went wrong' })
  ).toBeVisible()
  response = []
  status = 200
  await page
    .locator('[data-state="error"]')
    .getByRole('button', { name: 'Try again' })
    .click()
  await expect(page.getByText('No controls yet', { exact: true })).toBeVisible()
  await expect(page.locator('[data-state="error"]')).toHaveCount(0)
})

test('library evaluation stays loading until the coverage response completes', async ({
  page,
}) => {
  await installApi(page)
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/compliance-coverage**', async (route) => {
    await held
    await route.fallback()
  })
  await page.goto('/dashboard/controls')
  const row = page.getByRole('row').filter({
    has: page.getByRole('link', { name: 'Access review', exact: true }),
  })
  try {
    await expect(
      row.getByText('Loading evaluation…', { exact: true })
    ).toBeVisible()
    await expect(row).not.toContainText('Unknown')
  } finally {
    release()
  }
  await expect(row.getByText('Stale evidence', { exact: true })).toBeVisible()
  await expect(
    row.getByText('Loading evaluation…', { exact: true })
  ).toHaveCount(0)
})

test('evaluation failure preserves control details without inventing a pass', async ({
  page,
}) => {
  await installApi(page)
  await page.route('**/api/compliance-coverage**', (route) =>
    json(route, {}, 500)
  )
  await page.goto('/dashboard/controls/41')
  await expect(
    page.getByRole('heading', { name: 'Access review', exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Evaluation unavailable', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Access review record', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Qualified evidence', { exact: true })
  ).toHaveCount(0)
})

test('control library route serves the page instead of a missing route', async ({
  request,
}) => {
  const response = await request.get('/dashboard/controls', {
    headers: { Cookie: 'tc_session=synthetic-session' },
  })
  expect(response.status()).toBe(200)
})

for (const width of [360, 768, 1440]) {
  test(`control screens remain usable at ${width}px with keyboard and accessibility checks`, async ({
    page,
  }, testInfo) => {
    await installApi(page)
    await acknowledgeControlPatch(page)
    await page.setViewportSize({ width, height: 900 })
    const evidenceDir = path.resolve('../../artifacts/acceptance/TC-15-042')
    mkdirSync(path.join(evidenceDir, 'screenshots'), { recursive: true })
    for (const route of ['/dashboard/controls', '/dashboard/controls/41']) {
      await page.goto(route)
      await expect(
        page.getByRole('heading', {
          name: route.endsWith('41') ? 'Access review' : 'Control library',
          exact: true,
        })
      ).toBeVisible()
      await expect(
        page.locator('#main-content [data-state="loading"]')
      ).toHaveCount(0)
      if (!route.endsWith('41')) {
        const search = page.getByLabel('Search controls')
        await search.focus()
        await expect(search).toBeFocused()
        await page.keyboard.press('Tab')
        await expect(page.getByLabel('Filter lifecycle')).toBeFocused()
      }
      await expect(page.locator('#main-content')).toHaveJSProperty(
        'scrollWidth',
        await page.locator('#main-content').evaluate((el) => el.clientWidth)
      )
      const result = await new AxeBuilder({ page })
        .include('#main-content')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
      const violations = result.violations.map((item) => ({
        id: item.id,
        impact: item.impact,
        nodes: item.nodes.length,
      }))
      const name = route.endsWith('41') ? 'detail' : 'library'
      writeFileSync(
        path.join(evidenceDir, `axe-${name}-${width}.json`),
        JSON.stringify(
          { width, violationCount: violations.length, violations },
          null,
          2
        )
      )
      expect(
        violations.filter((item) =>
          ['critical', 'serious'].includes(item.impact || '')
        )
      ).toEqual([])
      await page.screenshot({
        path: path.join(evidenceDir, 'screenshots', `${name}-${width}.png`),
        fullPage: true,
      })
      await testInfo.attach(`${name}-${width}`, {
        path: path.join(evidenceDir, 'screenshots', `${name}-${width}.png`),
        contentType: 'image/png',
      })
      await testInfo.attach(`axe-${name}-${width}`, {
        path: path.join(evidenceDir, `axe-${name}-${width}.json`),
        contentType: 'application/json',
      })
      if (!route.endsWith('41')) continue
      const steps: string[] = []
      const team = page.getByLabel('Owner team')
      for (let index = 0; index < 80; index += 1) {
        await page.keyboard.press('Tab')
        const label = await focusedLabel(page)
        steps.push(label)
        expect(label, steps.join(' > ')).not.toBe('')
        expect(label, steps.join(' > ')).not.toBe('body')
        if (await team.evaluate((el) => el === document.activeElement)) break
      }
      expect(steps.at(-1), steps.join(' > ')).toBe('Owner team')
      expect(steps.at(-2), steps.join(' > ')).toBe('Owner')
      await expect(team).toBeFocused()
      await page.keyboard.press('End')
      await page.keyboard.type(' ops')
      await expect(team).toBeFocused()
      await expect(team).toHaveValue('Security ops')
      await page.keyboard.press('Tab')
      await expect(page.getByLabel('Lifecycle', { exact: true })).toBeFocused()
      await page.keyboard.press('Tab')
      const save = page.getByRole('button', {
        name: 'Save changes',
        exact: true,
      })
      await expect(save).toBeFocused()
      await page.keyboard.press('Enter')
      const saved = page.getByText('Changes saved', { exact: true })
      await expect(saved).toBeVisible()
      await expect(saved).toBeFocused()
    }
  })
}

test('successful evidence review refreshes expiry and verification state', async ({
  page,
}) => {
  await installApi(page)
  let verified = true
  await page.route('**/api/compliance/controls/41/evidence', (route) =>
    json(route, [
      {
        id: 61,
        verified,
        stale: true,
        expired: true,
        evidence: {
          title: 'Access review record',
          source_type: 'manual',
          created_at: null,
        },
      },
    ])
  )
  await page.route('**/api/compliance/controls/41/evidence/61', (route) => {
    verified = false
    return json(route, {
      id: 61,
      verified,
      stale: false,
      expired: false,
      evidence: {
        title: 'Access review record',
        source_type: 'manual',
        created_at: null,
      },
    })
  })
  await page.goto('/dashboard/controls/41')
  await page
    .getByRole('button', { name: 'Mark unverified', exact: true })
    .click()
  await expect(
    page.getByText('Evidence review saved', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Verify evidence link', exact: true })
  ).toBeVisible()
  await expect(page.getByText('Expired', { exact: true })).toBeVisible()
})

test('unverifying an old link refreshes its newly stale freshness', async ({
  page,
}) => {
  await installApi(page)
  let verified = true
  await page.route('**/api/compliance/controls/41/evidence', (route) =>
    json(route, [
      {
        id: 61,
        verified,
        stale: !verified,
        expired: false,
        evidence: {
          title: 'Access review record',
          source_type: 'manual',
          created_at: '2026-01-01T00:00:00Z',
        },
      },
    ])
  )
  await page.route('**/api/compliance/controls/41/evidence/61', (route) => {
    verified = false
    return json(route, {
      id: 61,
      verified,
      stale: true,
      expired: false,
      evidence: {
        title: 'Access review record',
        source_type: 'manual',
        created_at: '2026-01-01T00:00:00Z',
      },
    })
  })
  await page.goto('/dashboard/controls/41')
  await expect(
    page.getByText('Current according to the latest check')
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'Mark unverified', exact: true })
    .click()
  await expect(page.getByText('Needs refresh', { exact: true })).toBeVisible()
})

test('confirmed review with failed freshness read remains an explicit partial success', async ({
  page,
}) => {
  await installApi(page)
  let reviewed = false
  await page.route('**/api/compliance/controls/41/evidence', (route) =>
    reviewed ? json(route, {}, 500) : route.fallback()
  )
  await page.route('**/api/compliance/controls/41/evidence/61', (route) => {
    reviewed = true
    return json(route, {
      id: 61,
      verified: false,
      stale: false,
      expired: false,
      evidence: {
        title: 'Access review record',
        source_type: 'manual',
        created_at: null,
      },
    })
  })
  await page.goto('/dashboard/controls/41')
  await page
    .getByRole('button', { name: 'Mark unverified', exact: true })
    .click()
  await expect(
    page.getByText('Evidence review saved', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText('Freshness unavailable', { exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Retry freshness check' })
  ).toBeEnabled()
})
