import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const output = join(process.cwd(), 'test-results/session-expiry')
async function checkpoint(phase: string, width: number) {
  const directory = process.env.TC_SESSION_CHECKPOINT_DIR
  if (!directory)
    throw new Error('Run through the PostgreSQL session-expiry test')
  const marker = join(directory, `${phase}-${width}`)
  writeFileSync(`${marker}.json`, JSON.stringify({ phase, width }))
  await expect.poll(() => existsSync(`${marker}.ack`)).toBe(true)
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
  // The installed reporter records Evaluate, not its credential argument. The
  // owning harness also scans report archives before permitting artifact upload.
  await page
    .getByLabel('Password', { exact: true })
    .evaluate((input, value) => {
      if (!(input instanceof HTMLInputElement) || input.type !== 'password')
        throw new Error('Password control unavailable')
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value'
      )?.set
      if (!setter) throw new Error('Password control unavailable')
      setter.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }, password)
  await page.getByLabel('Keep me signed in').setChecked(remember)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard\/security$/)
  await expect(
    page.getByRole('region', { name: 'Active sessions', exact: true })
  ).toBeVisible()
}

async function visibleCheck(page: Page) {
  const result = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/auth/me'
  )
  // Exercise the real DOM visibility-return handler; do not replace /me or its
  // response. Unit tests separately cover an actually hidden document/timer.
  await page.evaluate(() =>
    document.dispatchEvent(new Event('visibilitychange'))
  )
  return result
}

async function axe(
  page: Page,
  width: number,
  state: 'warning' | 'unavailable'
) {
  const result = await new AxeBuilder({ page })
    .include('[role="status"][aria-label="Session expiry"]')
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  mkdirSync(output, { recursive: true })
  writeFileSync(
    join(output, `axe-${state}-${width}.json`),
    JSON.stringify(
      {
        state,
        width,
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
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true)
}

for (const remember of [false, true]) {
  test(`real ${remember ? 'remembered session retry and revocation' : 'ordinary session policy shortening and expiry'}`, async ({
    page,
    context,
    baseURL,
  }) => {
    const fixture = process.env.TC_SESSION_FIXTURE_FILE
    if (!fixture)
      throw new Error('Run through the PostgreSQL session-expiry test')
    const data = JSON.parse(readFileSync(fixture, 'utf8')) as {
      own: string
      foreign: string
      password: string
    }
    const width = remember ? 1440 : 360
    await page.setViewportSize({ width, height: 900 })
    const denied: string[] = []
    await context.route('**/*', (route) => {
      const origin = new URL(route.request().url()).origin
      if (origin === new URL(baseURL!).origin) return route.continue()
      denied.push(origin)
      return route.abort('blockedbyclient')
    })
    await login(
      page,
      remember ? data.foreign : data.own,
      data.password,
      remember
    )
    const cookie = (await context.cookies()).find(
      (item) => item.name === 'tc_session'
    )
    expect(!!cookie).toBe(true)
    expect(cookie!.expires > 0).toBe(remember)
    expect(cookie!.httpOnly).toBe(true)
    const initial = await page.request.get('/api/auth/me')
    expect(initial.status()).toBe(200)
    const initialTiming = await initial.json()
    expect(
      initialTiming.session_expires_at - initialTiming.server_time
    ).toBeGreaterThan(300)
    const banner = page.getByRole('status', {
      name: 'Session expiry',
      exact: true,
    })
    await expect(banner).toHaveCount(0)
    const writes: string[] = []
    page.on('request', (request) => {
      if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()))
        writes.push(new URL(request.url()).pathname)
    })
    await checkpoint('shorten', width)
    const shortened = await visibleCheck(page)
    expect(shortened.status()).toBe(200)
    const timing = await shortened.json()
    expect(timing.session_expires_at).toBeLessThan(
      initialTiming.session_expires_at
    )
    expect(timing.session_expires_at - timing.server_time).toBeLessThanOrEqual(
      120
    )
    expect(shortened.headers()['set-cookie']).toBeUndefined()
    await expect(banner).toContainText('Save your work')
    await expect(banner).toContainText('sign in again')
    await expect(banner.getByRole('button')).toHaveCount(0)
    if (!remember) {
      for (const view of [360, 768, 1440]) {
        await page.setViewportSize({ width: view, height: 900 })
        await axe(page, view, 'warning')
      }
    } else {
      await context.setOffline(true)
      await page.evaluate(() =>
        document.dispatchEvent(new Event('visibilitychange'))
      )
      await expect(banner).toContainText('Could not check')
      await expect(banner).not.toContainText('expires in')
      await axe(page, width, 'unavailable')
      await context.setOffline(false)
      await banner.getByRole('button', { name: 'Check session' }).press('Enter')
      await expect(banner).toContainText('Save your work')
      await expect(banner).not.toContainText('Could not check')
    }
    await checkpoint('warning', width)
    expect(
      (await context.cookies()).find((item) => item.name === 'tc_session')
        ?.value === cookie!.value
    ).toBe(true)
    await checkpoint(remember ? 'revoke' : 'expire', width)
    if (remember) {
      expect((await visibleCheck(page)).status()).toBe(401)
    } else {
      const expiryResponse = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === '/api/auth/me' &&
          response.status() === 401
      )
      const final = await visibleCheck(page)
      expect(final.status()).toBe(200)
      await expect(banner).toContainText('less than a minute')
      const expired = await expiryResponse
      expect(expired.request().method()).toBe('GET')
    }
    await expect(page).toHaveURL(/\/login(?:\?|$)/)
    expect((await page.request.get('/api/auth/me')).status()).toBe(401)
    expect(writes).toEqual([])
    expect(denied).toEqual([])
    await checkpoint('done', width)
  })
}
