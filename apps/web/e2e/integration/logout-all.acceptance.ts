import {
  expect,
  test,
  type BrowserContext,
  type CDPSession,
  type Page,
} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

type Fixture = { own: string; foreign: string; password: string }
const path = '/api/auth/sessions/revoke-all'
const output = join(process.cwd(), 'test-results/logout-all')

async function checkpoint(phase: string, width: number) {
  const directory = process.env.TC_LOGOUT_CHECKPOINT_DIR
  if (!directory) throw new Error('Run through the PostgreSQL logout-all test')
  const marker = join(directory, `${phase}-${width}`)
  writeFileSync(`${marker}.json`, JSON.stringify({ phase, width }))
  await expect.poll(() => existsSync(`${marker}.ack`)).toBe(true)
}

async function localOnly(context: BrowserContext, baseURL: string) {
  const denied: string[] = []
  await context.route('**/*', async (route) => {
    const target = new URL(route.request().url())
    if (target.origin === new URL(baseURL).origin) return route.continue()
    denied.push(target.origin)
    return route.abort('blockedbyclient')
  })
  return denied
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

async function login(
  page: Page,
  email: string,
  password: string,
  remember: boolean
) {
  await page.goto('/login?next=/dashboard/security')
  await page
    .getByLabel('Email', { exact: true })
    .pressSequentially(email, { delay: 1 })
  await enterPassword(page, password)
  await page.getByLabel('Keep me signed in').setChecked(remember)
  const response = page.waitForResponse(
    (res) =>
      new URL(res.url()).pathname === '/api/auth/login' &&
      res.request().method() === 'POST'
  )
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  expect((await response).status()).toBe(200)
  await expect(page).toHaveURL(/\/dashboard\/security$/)
  await expect(
    page.getByRole('region', { name: 'Active sessions', exact: true })
  ).toBeVisible()
  const cookie = (await page.context().cookies()).find(
    (item) => item.name === 'tc_session'
  )
  expect(!!cookie).toBe(true)
  // Never include the signed cookie value in assertion output or reports.
  expect(cookie!.expires > 0).toBe(remember)
  expect(cookie!.httpOnly).toBe(true)
  expect(cookie!.sameSite).toBe('Lax')
}

async function axe(page: Page, width: number, state: 'page' | 'dialog') {
  const result = await new AxeBuilder({ page })
    .include(
      state === 'page'
        ? 'section[aria-label="Active sessions"]'
        : '[role="alertdialog"]'
    )
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  mkdirSync(output, { recursive: true })
  // Persist full findings before asserting: a failed run must retain diagnostic data.
  writeFileSync(
    join(output, `axe-${state}-${width}.json`),
    JSON.stringify(
      {
        width,
        state,
        violationCount: result.violations.length,
        violations: result.violations,
      },
      null,
      2
    )
  )
  await page.screenshot({
    path: join(output, `${state}-${width}.png`),
    fullPage: true,
  })
  expect(result.violations).toEqual([])
}

for (const width of [360, 768, 1440]) {
  test(`real logout-all across three browser contexts at ${width}`, async ({
    browser,
    baseURL,
  }) => {
    const raw = process.env.TC_LOGOUT_FIXTURE
    if (!raw) throw new Error('Run through the PostgreSQL logout-all test')
    const data = JSON.parse(raw) as Fixture
    const contexts: BrowserContext[] = []
    let release = () => {}
    let responseObserver: CDPSession | undefined
    try {
      for (let index = 0; index < 3; index++) {
        contexts.push(
          await browser.newContext({
            baseURL,
            viewport: { width, height: 900 },
            storageState: { cookies: [], origins: [] },
            extraHTTPHeaders: {
              Origin: baseURL!,
              Referer: `${baseURL}/dashboard/security`,
            },
          })
        )
      }
      const external = await Promise.all(
        contexts.map((context) => localOnly(context, baseURL!))
      )
      const [a, b, foreign] = await Promise.all(
        contexts.map((context) => context.newPage())
      )
      for (const context of contexts)
        expect(await context.cookies()).toEqual([])
      await login(a, data.own, data.password, false)
      await login(b, data.own, data.password, true)
      await login(foreign, data.foreign, data.password, false)
      const sessions = await a.request.get('/api/auth/sessions')
      expect(sessions.status()).toBe(200)
      const own = (await sessions.json()).sessions as { id: number }[]
      expect(own).toHaveLength(2)
      expect(new Set(own.map((item) => item.id)).size).toBe(2)
      const foreignBefore = await (
        await foreign.request.get('/api/auth/sessions')
      ).json()
      await a.reload()
      const region = a.locator('section[aria-label="Active sessions"]')
      const trigger = region.getByRole('button', {
        name: 'Sign out everywhere',
        exact: true,
        includeHidden: true,
      })
      await expect(
        region.getByText('2 active sessions', { exact: true })
      ).toBeVisible()
      await expect(
        region.getByRole('button', {
          name: 'Sign out all other devices (1)',
          exact: true,
        })
      ).toBeVisible()
      await checkpoint('before', width)
      await axe(a, width, 'page')
      expect(
        await a.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth
        )
      ).toBe(true)
      const posts: string[] = []
      a.on('request', (request) => {
        if (
          new URL(request.url()).pathname === path &&
          request.method() === 'POST'
        )
          posts.push(request.method())
      })
      await trigger.focus()
      await a.keyboard.press('Enter')
      const dialog = a.getByRole('alertdialog', {
        name: 'Sign out everywhere?',
      })
      const cancel = dialog.getByRole('button', { name: 'Cancel', exact: true })
      await expect(cancel).toBeFocused()
      await axe(a, width, 'dialog')
      expect(
        await a.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth
        )
      ).toBe(true)
      await a.keyboard.press('Tab')
      await expect(
        dialog.getByRole('button', { name: 'Sign out everywhere', exact: true })
      ).toBeFocused()
      await a.keyboard.press('Tab')
      expect(
        await dialog.evaluate((element) =>
          element.contains(document.activeElement)
        )
      ).toBe(true)
      await a.keyboard.press('Escape')
      await expect(dialog).toHaveCount(0)
      await expect(trigger).toBeFocused()
      await trigger.press('Enter')
      await cancel.press('Enter')
      await expect(dialog).toHaveCount(0)
      expect(posts).toEqual([])
      expect((await a.request.get('/api/auth/me')).status()).toBe(200)
      // Hold only dispatch timing; the request is continued to the actual API.
      const gate = new Promise<void>((resolve) => {
        release = resolve
      })
      await a.route(`**${path}`, async (route) => {
        await gate
        await route.continue()
      })
      await trigger.press('Enter')
      const response = a.waitForResponse(
        (res) =>
          new URL(res.url()).pathname === path &&
          res.request().method() === 'POST'
      )
      await dialog
        .getByRole('button', { name: 'Sign out everywhere', exact: true })
        .press('Enter')
      await expect.poll(() => posts.length).toBe(1)
      await expect(
        dialog.getByRole('button', { name: 'Working…' })
      ).toBeDisabled()
      await expect(cancel).toBeDisabled()
      await expect(trigger).toBeDisabled()
      await expect(
        region.getByRole('button', {
          name: 'Signing out...',
          includeHidden: true,
        })
      ).toBeDisabled()
      await expect(a).toHaveURL(/\/dashboard\/security$/)
      // Retain the real response across native navigation without delaying it.
      responseObserver = await a.context().newCDPSession(a)
      await responseObserver.send('Network.enable')
      await responseObserver.send('Network.configureDurableMessages', {
        maxTotalBufferSize: 1024 * 1024,
      })
      release()
      const acknowledged = await response
      expect(acknowledged.status()).toBe(200)
      expect(await acknowledged.json()).toEqual({ ok: true, revoked: 2 })
      await expect(a).toHaveURL(/\/login$/)
      expect(
        (await contexts[0].cookies()).some(
          (cookie) => cookie.name === 'tc_session'
        )
      ).toBe(false)
      expect((await a.request.get('/api/auth/me')).status()).toBe(401)
      expect((await b.request.get('/api/auth/me')).status()).toBe(401)
      await b.reload()
      await expect(b).toHaveURL(/\/login(?:\?|$)/)
      expect((await foreign.request.get('/api/auth/me')).status()).toBe(200)
      expect(
        await (await foreign.request.get('/api/auth/sessions')).json()
      ).toEqual(foreignBefore)
      await foreign.reload()
      await expect(
        foreign.getByRole('region', { name: 'Active sessions', exact: true })
      ).toBeVisible()
      expect(posts).toEqual(['POST'])
      expect(external.flat()).toEqual([])
      await checkpoint('after', width)
    } finally {
      release()
      try {
        await responseObserver?.detach()
      } finally {
        await Promise.all(contexts.map((context) => context.close()))
      }
    }
  })
}
