import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

type Questionnaire = { id: number; display_id: string; filename: string }
type Fixture = {
  own: string
  password: string
  questionnaires: Record<string, Questionnaire>
}
const output = join(process.cwd(), 'test-results/questionnaire-ack')
async function checkpoint(phase: string, width: number) {
  const directory = process.env.TC_QNR_ACK_CHECKPOINT_DIR
  if (!directory)
    throw new Error('Run through the migrated PostgreSQL questionnaire test')
  const marker = join(directory, `${phase}-${width}`)
  writeFileSync(`${marker}.json`, JSON.stringify({ phase, width }))
  await expect.poll(() => existsSync(`${marker}.ack`)).toBe(true)
}
// Keep the credential in a separate evaluate argument: the installed Playwright
// renderer records Evaluate/locator, not that argument. The report regression
// checks both installed reporters, and the owning harness scans uploaded payloads.
async function enterPassword(page: Page, password: string) {
  await page
    .getByLabel('Password', { exact: true })
    .evaluate((input, value) => {
      if (!(input instanceof HTMLInputElement) || input.type !== 'password') {
        throw new Error('Password control is unavailable')
      }
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value'
      )?.set
      if (!setter) throw new Error('Password control is unavailable')
      // Use the native setter so React observes the following real input event.
      setter.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }, password)
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
    join(output, `axe-${state}-${width}.json`),
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
    path: join(output, `${state}-${width}.png`),
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
  test(`real questionnaire 403 and 200 acknowledgement at ${width}`, async ({
    page,
    baseURL,
  }) => {
    const fixture = process.env.TC_QNR_ACK_FIXTURE
    if (!fixture)
      throw new Error('Run through the migrated PostgreSQL questionnaire test')
    const data = JSON.parse(readFileSync(fixture, 'utf8')) as Fixture
    const qnr = data.questionnaires[String(width)]
    const external: string[] = []
    // Local real routes continue unchanged; only external network is prohibited.
    await page.context().route('**/*', (route) => {
      const url = new URL(route.request().url())
      if (url.origin === new URL(baseURL!).origin) return route.continue()
      external.push(url.origin)
      return route.abort('blockedbyclient')
    })
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/login?next=/dashboard/questionnaires')
    await page.getByLabel('Email', { exact: true }).fill(data.own)
    await enterPassword(page, data.password)
    const login = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === '/api/auth/login' &&
        r.request().method() === 'POST'
    )
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    expect((await login).status()).toBe(200)
    await expect(page).toHaveURL(/\/dashboard\/questionnaires$/)
    await page.getByLabel('Archive filter').selectOption('include')
    const row = page.getByRole('listitem').filter({
      has: page.getByRole('link', { name: qnr.filename, exact: true }),
    })
    await expect(row).toBeVisible()
    const trigger = row.getByRole('button', {
      name: `Actions for ${qnr.display_id}`,
    })
    await checkpoint('ready', width)
    await trigger.press('Enter')
    await page.getByRole('menuitem', { name: 'Edit metadata' }).press('Enter')
    const dialog = page.getByRole('dialog')
    const metadata = () =>
      page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname ===
            `/api/questionnaires/${qnr.id}/metadata` &&
          r.request().method() === 'PATCH'
      )
    let response = metadata()
    await dialog.getByRole('button', { name: 'ISO 27001' }).press('Enter')
    expect((await response).status()).toBe(403)
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(
      dialog.getByRole('button', { name: 'ISO 27001' })
    ).toHaveAttribute('aria-pressed', 'true')
    await expect(row.locator('[title="framework: ISO 27001"]')).toHaveCount(0)
    await capture(page, width, 'metadata-error', '[role="dialog"]')
    await checkpoint('metadata-denied', width)
    response = metadata()
    await dialog.getByRole('button', { name: 'Retry saving' }).press('Enter')
    expect((await response).status()).toBe(200)
    await expect(dialog.getByRole('status')).toHaveText('Metadata saved.')
    await expect(row.locator('[title="framework: ISO 27001"]')).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(trigger).toBeFocused()
    await checkpoint('metadata-saved', width)
    await trigger.press('Enter')
    const restore = () =>
      page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname ===
            `/api/questionnaires/${qnr.id}/restore` &&
          r.request().method() === 'POST'
      )
    response = restore()
    await page.getByRole('menuitem', { name: 'Restore' }).press('Enter')
    expect((await response).status()).toBe(403)
    await expect(row.getByRole('alert')).toBeVisible()
    await expect(row.getByText('Archived', { exact: true })).toBeVisible()
    await capture(
      page,
      width,
      'restore-error',
      '[aria-label="Questionnaire registry"]'
    )
    await checkpoint('restore-denied', width)
    response = restore()
    await row.getByRole('button', { name: 'Retry restore' }).press('Enter')
    expect((await response).status()).toBe(200)
    await expect(page.getByText('Questionnaire restored.')).toBeVisible()
    await expect(row.getByText('Archived', { exact: true })).toHaveCount(0)
    await checkpoint('restored', width)
    await page.reload()
    // The default filter now includes the genuinely restored row with persisted metadata.
    await expect(row.locator('[title="framework: ISO 27001"]')).toBeVisible()
    await expect(row.getByText('Archived', { exact: true })).toHaveCount(0)
    expect(external).toEqual([])
  })
}
