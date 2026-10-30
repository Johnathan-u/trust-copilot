import { expect, test, type Page, type Route } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

test.use({ storageState: { cookies: [], origins: [] } })
const output = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-15-017a'
)
const record = {
  id: 41,
  display_id: 'QNR-ACK-41',
  filename: 'Acknowledgement questionnaire.xlsx',
  status: 'parsed',
  created_at: '2026-10-01T12:00:00Z',
  deleted_at: '2026-10-02T12:00:00Z',
  frameworks: ['SOC 2'],
  subject_areas: ['Other'],
}
const json = (route: Route, data: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  })
async function setup(page: Page) {
  const state = {
    row: { ...record },
    calls: [] as string[],
    mutation: async (route: Route) =>
      json(route, { detail: 'Permission denied' }, 403),
  }
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
        email: 'operator@example.com',
        display_name: 'Synthetic Operator',
        workspace_id: 7,
        workspace_name: 'Synthetic workspace',
        workspace_slug: 'synthetic',
        role: 'editor',
        workspaces: [
          {
            id: 7,
            name: 'Synthetic workspace',
            slug: 'synthetic',
            role: 'editor',
          },
        ],
        permissions: {
          can_edit: true,
          can_admin: false,
          can_review: true,
          can_export: false,
        },
        needs_onboarding: false,
        subscription: { status: 'trialing' },
        mfa_enrolled: true,
        mfa_required_for_workspace: false,
        workspace_auth_policy: {
          mfa_required: false,
          session_max_age_seconds: null,
        },
      })
    if (
      p.startsWith('/api/questionnaires/') &&
      route.request().method() !== 'GET'
    ) {
      state.calls.push(p)
      return state.mutation(route)
    }
    if (p === '/api/questionnaires/') return json(route, { items: [state.row] })
    if (p.endsWith('/unread-count')) return json(route, { count: 0 })
    if (p === '/api/auth/alerts') return json(route, { alerts: [] })
    if (p === '/api/workspaces/creation-policy')
      return json(route, { can_create: false })
    return json(route, {})
  })
  await page.goto('/dashboard/questionnaires')
  await expect(page.getByRole('link', { name: record.filename })).toBeVisible()
  return state
}
async function edit(page: Page) {
  const trigger = page.getByRole('button', {
    name: `Actions for ${record.display_id}`,
  })
  await trigger.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('menuitem', { name: 'Edit metadata' }).focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect
    .poll(() => dialog.evaluate((el) => el.contains(document.activeElement)))
    .toBe(true)
  await dialog.getByRole('button', { name: 'ISO 27001' }).press('Enter')
  return { dialog, trigger }
}
async function capture(
  page: Page,
  width: number,
  state: string,
  selector: string
) {
  if (state === 'restore-error') {
    await page
      .getByRole('region', { name: 'Questionnaire registry' })
      .getByRole('alert')
      .scrollIntoViewIfNeeded()
  } else if (state === 'acknowledged') {
    await page.getByText('Questionnaire restored.').scrollIntoViewIfNeeded()
  }
  const results = await new AxeBuilder({ page })
    .include(selector)
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  mkdirSync(output, { recursive: true })
  writeFileSync(
    path.join(output, `axe-${state}-${width}.json`),
    JSON.stringify(
      {
        width,
        state,
        violationCount: results.violations.length,
        violations: results.violations,
      },
      null,
      2
    )
  )
  await page.screenshot({
    path: path.join(output, `${state}-${width}.png`),
    fullPage: true,
  })
  expect(results.violations).toEqual([])
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true)
}
for (const width of [360, 768, 1440]) {
  test(`metadata and restore failure/retry, keyboard and axe at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const state = await setup(page)
    const { dialog, trigger } = await edit(page)
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(
      dialog.getByRole('button', { name: 'ISO 27001' })
    ).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('[title="framework: ISO 27001"]')).toHaveCount(0)
    // Both directions wrap within the real dialog; Escape restores the row trigger.
    const buttons = dialog.getByRole('button')
    await buttons.last().focus()
    await page.keyboard.press('Tab')
    await expect(buttons.first()).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(buttons.last()).toBeFocused()
    await capture(page, width, 'metadata-error', '[role="dialog"]')
    let release!: () => void
    const pending = new Promise<void>((done) => {
      release = done
    })
    state.mutation = async (route) => {
      await pending
      return json(route, { ok: true })
    }
    await dialog.getByRole('button', { name: 'Retry saving' }).click()
    await expect(dialog.getByRole('status')).toHaveText('Saving…')
    await expect(
      dialog.getByRole('button', { name: 'ISO 27001' })
    ).toBeDisabled()
    await page.keyboard.press('Enter')
    expect(state.calls).toHaveLength(2)
    release()
    await expect(dialog.getByRole('status')).toHaveText('Metadata saved.')
    await page.keyboard.press('Escape')
    await expect(trigger).toBeFocused()
    await expect(page.locator('[title="framework: ISO 27001"]')).toBeVisible()
    await trigger.press('Enter')
    await page.getByRole('menuitem', { name: 'Edit metadata' }).press('Enter')
    await expect(
      page.getByRole('button', { name: 'ISO 27001' })
    ).toHaveAttribute('aria-pressed', 'true')
    await page.keyboard.press('Escape')
    await expect(trigger).toBeFocused()
    state.mutation = async (route) =>
      json(route, { detail: 'Permission denied' }, 403)
    await trigger.press('Enter')
    await page.getByRole('menuitem', { name: 'Restore' }).press('Enter')
    await expect(
      page
        .getByRole('region', { name: 'Questionnaire registry' })
        .getByRole('alert')
    ).toBeVisible()
    await expect(page.getByText('Archived', { exact: true })).toBeVisible()
    await capture(
      page,
      width,
      'restore-error',
      '[aria-label="Questionnaire registry"]'
    )
    state.mutation = async (route) =>
      json(route, { ok: true, id: record.id, display_id: record.display_id })
    await page.getByRole('button', { name: 'Retry restore' }).press('Enter')
    await expect(page.getByText('Questionnaire restored.')).toBeVisible()
    await expect(page.getByText('Archived', { exact: true })).toHaveCount(0)
    await capture(
      page,
      width,
      'acknowledged',
      '[aria-label="Questionnaire registry"]'
    )
  })
}
test('synthetic transport abort preserves draft and archive state separately from API rejection', async ({
  page,
}) => {
  const state = await setup(page)
  state.mutation = (route) => route.abort('failed')
  const { dialog, trigger } = await edit(page)
  await expect(dialog.getByRole('alert')).toContainText('Could not confirm')
  await expect(
    dialog.getByRole('button', { name: 'ISO 27001' })
  ).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
  await trigger.click()
  await page.getByRole('menuitem', { name: 'Restore' }).click()
  await expect(
    page
      .getByRole('region', { name: 'Questionnaire registry' })
      .getByRole('alert')
  ).toContainText('Could not confirm')
  await expect(page.getByText('Archived', { exact: true })).toBeVisible()
  await expect(page.locator('[title="framework: ISO 27001"]')).toHaveCount(0)
})
