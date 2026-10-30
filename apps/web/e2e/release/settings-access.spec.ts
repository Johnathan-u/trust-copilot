import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-16-BUG-001'
)

type RoleName = 'admin' | 'member'

const workspaces = [
  { id: 7, name: 'Synthetic Workspace', slug: 'synthetic', role: 'admin' },
  {
    id: 8,
    name: 'Synthetic Second Workspace',
    slug: 'synthetic-b',
    role: 'member',
  },
]

function syntheticMe(role: RoleName) {
  const canAdmin = role === 'admin'
  return {
    id: 42,
    email: 'synthetic.member@example.com',
    display_name: 'Synthetic Member',
    workspace_id: 7,
    workspace_name: 'Synthetic Workspace',
    workspace_slug: 'synthetic',
    role: canAdmin ? 'admin' : 'member',
    workspaces: workspaces.map((workspace) => ({
      ...workspace,
      role: canAdmin ? 'admin' : 'member',
    })),
    permissions: {
      can_edit: canAdmin,
      can_review: true,
      can_admin: canAdmin,
      can_export: canAdmin,
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

function fulfillJson(
  route: { fulfill: (opts: object) => Promise<void> },
  body: unknown
) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installApi(page: Page, role: RoleName, holdMe = false) {
  let releaseMe: () => void = () => {}
  const held = new Promise<void>((resolve) => {
    releaseMe = resolve
  })
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/api/auth/me')) {
      if (holdMe) await held
      return fulfillJson(route, syntheticMe(role))
    }
    if (pathname.includes('/unread-count'))
      return fulfillJson(route, { count: 0 })
    if (pathname.includes('/api/auth/alerts'))
      return fulfillJson(route, { alerts: [] })
    if (pathname.includes('/api/in-app-notifications'))
      return fulfillJson(route, { items: [] })
    if (pathname.replace(/\/$/, '') === '/api/workspaces/creation-policy') {
      return fulfillJson(route, { can_create_workspace: true })
    }
    return fulfillJson(route, {})
  })
  return releaseMe
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

async function openSettings(page: Page, role: RoleName) {
  await installApi(page, role)
  await allowSyntheticSession(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/dashboard/settings')
}

test.describe('settings page role gate', () => {
  test.describe.configure({ timeout: 90_000 })

  test('an admin sees admin-only sections and no not-authorized state', async ({
    page,
  }) => {
    await openSettings(page, 'admin')
    await expect(
      page.getByRole('heading', { name: 'Settings', level: 1 })
    ).toBeVisible()
    await expect(page.getByTestId('settings-billing')).toBeVisible()
    await expect(page.getByTestId('settings-create-workspace')).toBeVisible()
    await expect(page.getByTestId('settings-account-security')).toBeVisible()
    await expect(page.getByTestId('settings-workspace-switch')).toBeVisible()
    await expect(page.getByTestId('settings-not-authorized')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Manage Billing' })
    ).toBeVisible()
  })

  test('a non-admin gets a not-authorized state without admin-only sections', async ({
    page,
  }) => {
    await openSettings(page, 'member')
    const denied = page.getByTestId('settings-not-authorized')
    await expect(denied).toBeVisible()
    await expect(
      denied.getByRole('heading', { name: 'Not authorized', level: 1 })
    ).toBeVisible()
    await expect(
      denied.getByRole('link', { name: 'Back to dashboard' })
    ).toHaveAttribute('href', '/dashboard')
    await expect(page.getByTestId('settings-account-security')).toBeVisible()
    await expect(
      page.getByRole('link', { name: 'Go to Account Security' })
    ).toBeVisible()
    await expect(page.getByTestId('settings-workspace-switch')).toBeVisible()
    await expect(page.getByTestId('settings-billing')).toHaveCount(0)
    await expect(page.getByTestId('settings-create-workspace')).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Manage Billing' })
    ).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Create workspace' })
    ).toHaveCount(0)

    const axe = await new AxeBuilder({ page })
      .include('[data-testid="settings-not-authorized"]')
      .analyze()
    mkdirSync(evidenceDir, { recursive: true })
    writeFileSync(
      path.join(evidenceDir, 'axe-not-authorized.json'),
      `${JSON.stringify(
        {
          name: 'settings-not-authorized',
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
    expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual([])
  })

  test('admin-only sections stay unmounted until the session resolves', async ({
    page,
  }) => {
    const releaseMe = await installApi(page, 'admin', true)
    await allowSyntheticSession(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard/settings')
    await expect(page.getByText('Loading workspace…')).toBeVisible()
    await expect(page.getByTestId('settings-loading')).toHaveCount(0)
    await expect(page.getByTestId('settings-billing')).toHaveCount(0)
    await expect(page.getByTestId('settings-create-workspace')).toHaveCount(0)
    await expect(page.getByTestId('settings-not-authorized')).toHaveCount(0)
    releaseMe()
    await expect(page.getByTestId('settings-billing')).toBeVisible()
    await expect(page.getByTestId('settings-not-authorized')).toHaveCount(0)
  })
})
