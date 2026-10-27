import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Locator, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-003a'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

const viewports = [
  { name: '360', width: 360, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '1440', width: 1440, height: 900 },
] as const

const themes = ['dark', 'light'] as const

const thirdPartyFontHosts = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'fonts.bunny.net',
  'use.typekit.net',
  'fast.fonts.net',
  'fonts.cdnfonts.com',
  'fontshare.com',
  'api.fontshare.com',
]

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

function watchRequests(page: Page): string[] {
  const urls: string[] = []
  page.on('request', (request) => {
    urls.push(request.url())
  })
  return urls
}

function assertSelfHostedFonts(pageUrl: string, urls: string[]) {
  const pageHost = new URL(pageUrl).hostname
  const fontUrls = urls.filter((url) =>
    /\.(?:woff2?|ttf|otf|eot)(?:$|\?)/i.test(url)
  )
  expect(fontUrls, 'expected a same-origin font file').not.toEqual([])
  for (const url of urls) {
    let host = ''
    try {
      host = new URL(url).hostname
    } catch {
      continue
    }
    const blocked = thirdPartyFontHosts.some(
      (name) => host === name || host.endsWith(`.${name}`)
    )
    expect(blocked, url).toBe(false)
  }
  for (const url of fontUrls) {
    expect(new URL(url).hostname, url).toBe(pageHost)
  }
}

async function openTheme(page: Page, theme: (typeof themes)[number]) {
  await page.addInitScript((value) => {
    document.documentElement.setAttribute('data-theme', value)
  }, theme)
  await page.goto(`/design-dialogs?theme=${theme}`)
  await expect(page.getByTestId('dialog-showcase')).toHaveAttribute(
    'data-expected-theme',
    theme
  )
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
}

async function focused(locator: Locator) {
  await expect(locator).toBeFocused()
}

test.describe('dialog focus and notifications', () => {
  test.describe.configure({ timeout: 120_000 })

  test('traps focus, restores it, and announces toasts without stealing the field', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openTheme(page, 'dark')

    const rename = page.getByRole('button', { name: 'Rename sample' })
    await rename.click()
    const dialog = page.getByRole('dialog', { name: 'Rename sample record' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-describedby', /.+/)
    await expect(
      dialog.getByText('Choose a new name for the synthetic sample record.')
    ).toBeVisible()
    const name = page.getByLabel('Record name')
    await focused(name)
    const notesInert = await page
      .locator('#working-notes')
      .evaluate((el) => el.closest('[inert]') !== null)
    expect(notesInert).toBe(true)

    await page.keyboard.press('Shift+Tab')
    await focused(page.getByRole('button', { name: 'Close' }))
    await page.keyboard.press('Tab')
    await focused(name)

    await page.getByRole('button', { name: 'Save name' }).focus()
    await page.keyboard.press('Tab')
    await focused(page.getByRole('button', { name: 'Close' }))
    await page.keyboard.press('Shift+Tab')
    await focused(page.getByRole('button', { name: 'Save name' }))

    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await focused(rename)

    const remove = page.getByRole('button', { name: 'Delete sample record' })
    await remove.click()
    const confirm = page.getByRole('alertdialog', {
      name: 'Delete sample record?',
    })
    await expect(confirm).toBeVisible()
    await expect(confirm.getByText('archived as a soft delete')).toBeVisible()
    await focused(page.getByRole('button', { name: 'Cancel' }))
    await page.keyboard.press('Escape')
    await expect(confirm).toHaveCount(0)
    await focused(remove)

    const drawerTrigger = page.getByRole('button', { name: 'Open side panel' })
    await drawerTrigger.click()
    const drawer = page.getByRole('dialog', { name: 'Navigation' })
    await expect(drawer).toBeVisible()
    await focused(page.getByRole('link', { name: 'Documents' }))
    await page.getByRole('link', { name: 'Questionnaires' }).focus()
    await page.keyboard.press('Tab')
    await focused(page.getByRole('button', { name: 'Close' }))
    await page.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
    await focused(drawerTrigger)

    const notes = page.getByLabel('Working notes')
    await notes.click()
    await notes.fill('draft')
    await notes.type(' ok')
    const status = page
      .getByRole('status')
      .filter({ hasText: 'Synthetic status saved.' })
    await expect(status).toBeVisible()
    await expect(status).toHaveAttribute('aria-live', 'polite')
    await focused(notes)
    await page.waitForTimeout(4500)
    await expect(status).toHaveCount(0)

    await notes.fill('draft')
    await notes.type(' err')
    const alert = page
      .getByRole('alert')
      .filter({ hasText: 'Synthetic error stayed on screen.' })
    await expect(alert).toBeVisible()
    await expect(alert).toHaveAttribute('aria-live', 'assertive')
    await focused(notes)
    await page.waitForTimeout(4500)
    await expect(alert).toBeVisible()
    const dismiss = page.getByRole('button', { name: 'Dismiss Save failed' })
    for (let i = 0; i < 16; i += 1) {
      if (
        await dismiss
          .evaluate((el) => el === document.activeElement)
          .catch(() => false)
      )
        break
      await page.keyboard.press('Tab')
    }
    await focused(dismiss)
    await page.keyboard.press('Enter')
    await expect(alert).toHaveCount(0)
  })

  test('reduced motion removes the toast transition', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openTheme(page, 'dark')
    await page.getByRole('button', { name: 'Show status' }).click()
    const duration = await page
      .locator('#tc-toast-status .tc-toast')
      .evaluate((el) => getComputedStyle(el).transitionDuration)
    expect(duration === '0s' || duration.startsWith('0s')).toBe(true)
  })

  test('an unknown theme query keeps the default dark theme', async ({
    page,
  }) => {
    await page.goto('/design-dialogs?theme=nope')
    await expect(page.locator('html')).not.toHaveAttribute(
      'data-theme',
      'light'
    )
    await expect(page.getByTestId('dialog-showcase')).toHaveAttribute(
      'data-expected-theme',
      'dark'
    )
  })

  test('notifications panel is a disclosure popover', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openTheme(page, 'dark')

    const bell = page.getByRole('button', {
      name: 'Notifications',
      exact: true,
    })
    const panel = page.locator('#sample-notifications')
    await expect(bell).toHaveAttribute('aria-expanded', 'false')
    await expect(bell).toHaveAttribute('aria-controls', 'sample-notifications')
    await expect(panel).toHaveCount(0)

    await bell.click()
    await expect(panel).toBeVisible()
    await expect(bell).toHaveAttribute('aria-expanded', 'true')
    await expect(panel).not.toHaveAttribute('aria-modal')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    const notesInert = await page
      .locator('#working-notes')
      .evaluate((el) => el.closest('[inert]') !== null)
    expect(notesInert).toBe(false)
    expect(await page.locator('[inert]').count()).toBe(0)

    await page.getByRole('button', { name: 'Close notifications' }).focus()
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Shift+Tab')
      if (await bell.evaluate((el) => el === document.activeElement)) break
    }
    await focused(bell)

    await page.getByRole('link', { name: 'Notification settings' }).focus()
    await page.keyboard.press('Tab')
    await focused(page.getByRole('link', { name: 'Page help' }))
    const leftPanel = await panel.evaluate(
      (el) => !el.contains(document.activeElement)
    )
    expect(leftPanel).toBe(true)

    await page.getByRole('link', { name: 'View audit log' }).focus()
    await page.keyboard.press('Escape')
    await expect(panel).toHaveCount(0)
    await focused(bell)
    await expect(bell).toHaveAttribute('aria-expanded', 'false')

    await bell.click()
    await expect(panel).toBeVisible()
    await page.getByLabel('Working notes').click()
    await expect(panel).toHaveCount(0)
    await focused(bell)
    await expect(bell).toHaveAttribute('aria-expanded', 'false')
    const notesInertAfter = await page
      .locator('#working-notes')
      .evaluate((el) => el.closest('[inert]') !== null)
    expect(notesInertAfter).toBe(false)
  })

  test('persistent regions receive toast text, and a rejected confirm announces an error', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openTheme(page, 'dark')

    const polite = page.locator('#tc-toast-status')
    const assertive = page.locator('#tc-toast-alert')
    await expect(polite).toHaveCount(1)
    await expect(assertive).toHaveCount(1)
    await expect(polite).toHaveAttribute('role', 'status')
    await expect(polite).toHaveAttribute('aria-live', 'polite')
    await expect(assertive).toHaveAttribute('role', 'alert')
    await expect(assertive).toHaveAttribute('aria-live', 'assertive')
    expect((await polite.innerText()).trim()).toBe('')
    expect((await assertive.innerText()).trim()).toBe('')

    await page.getByRole('button', { name: 'Show status' }).click()
    await expect(polite).toContainText('Synthetic status saved.')
    await expect(assertive).not.toContainText('Synthetic status saved.')
    await expect(polite).toHaveAttribute('aria-live', 'polite')
    await page.getByRole('button', { name: 'Dismiss Saved' }).click()
    expect((await polite.innerText()).trim()).toBe('')

    await page.getByRole('button', { name: 'Show error' }).click()
    await expect(assertive).toContainText('Synthetic error stayed on screen.')
    await expect(polite).not.toContainText('Synthetic error stayed on screen.')
    await expect(assertive).toHaveAttribute('aria-live', 'assertive')
    await page.getByRole('button', { name: 'Dismiss Save failed' }).click()

    const reject = page.getByRole('button', { name: 'Reject sample' })
    await reject.click()
    const confirm = page.getByRole('alertdialog', {
      name: 'Delete synthetic sample?',
    })
    await expect(confirm).toBeVisible()
    await focused(page.getByRole('button', { name: 'Cancel' }))
    await page.getByRole('button', { name: 'Remove sample' }).click()
    await expect(confirm).toHaveCount(0)
    await focused(reject)
    await expect(assertive).toContainText('Synthetic delete was rejected.')
    await expect(polite).not.toContainText('Synthetic delete was rejected.')
    await expect(assertive).toHaveAttribute('aria-live', 'assertive')
    await page.waitForTimeout(4500)
    await expect(assertive).toContainText('Synthetic delete was rejected.')
    await page.getByRole('button', { name: 'Dismiss Action failed' }).click()
    expect((await assertive.innerText()).trim()).toBe('')
  })

  test('info toasts leave after 4000ms and action toasts stay', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await openTheme(page, 'dark')

    await page.getByRole('button', { name: 'Show info' }).click()
    const info = page
      .getByRole('status')
      .filter({ hasText: 'Synthetic info saved.' })
    await expect(info).toBeVisible()
    await expect(info).toHaveAttribute('aria-live', 'polite')
    await page.waitForTimeout(4500)
    await expect(info).toHaveCount(0)

    await page.getByRole('button', { name: 'Show undo' }).click()
    const undoToast = page
      .getByRole('status')
      .filter({ hasText: 'Synthetic sample can be restored.' })
    const undo = page.getByRole('button', { name: 'Undo', exact: true })
    await expect(undoToast).toBeVisible()
    await expect(undo).toBeVisible()
    await page.waitForTimeout(4500)
    await expect(undoToast).toBeVisible()
    await undo.click()
    await expect(undoToast).toHaveCount(0)
    await expect(page.getByLabel('Working notes')).toHaveValue('restored')
  })

  for (const theme of themes) {
    test(`${theme} dialogs and toasts have no axe violations at 360, 768 and 1440`, async ({
      page,
    }) => {
      test.setTimeout(180_000)
      const requests = watchRequests(page)
      await page.setViewportSize({ width: 1440, height: 900 })
      await openTheme(page, theme)
      assertSelfHostedFonts(page.url(), requests)

      const states = [
        {
          id: 'dialog',
          open: async () => {
            await page.getByRole('button', { name: 'Show status' }).click()
            await page.getByRole('button', { name: 'Rename sample' }).click()
            await expect(
              page.getByRole('dialog', { name: 'Rename sample record' })
            ).toBeVisible()
            const status = page
              .locator('.tc-toast')
              .filter({ hasText: 'Synthetic status saved.' })
            await expect(status).toBeAttached()
            expect(await status.boundingBox()).not.toBeNull()
          },
          close: async () => {
            await page.keyboard.press('Escape')
            await expect(
              page.getByRole('dialog', { name: 'Rename sample record' })
            ).toHaveCount(0)
            const dismiss = page.getByRole('button', { name: 'Dismiss Saved' })
            if (await dismiss.count()) await dismiss.click()
          },
        },
        {
          id: 'confirm',
          open: async () => {
            await page.getByRole('button', { name: 'Show error' }).click()
            await page
              .getByRole('button', { name: 'Delete sample record' })
              .click()
            await expect(page.getByRole('alertdialog')).toBeVisible()
            const alert = page
              .locator('.tc-toast')
              .filter({ hasText: 'Synthetic error stayed on screen.' })
            await expect(alert).toBeAttached()
            expect(await alert.boundingBox()).not.toBeNull()
          },
          close: async () => {
            await page.keyboard.press('Escape')
            await expect(page.getByRole('alertdialog')).toHaveCount(0)
            await page
              .getByRole('button', { name: 'Dismiss Save failed' })
              .click()
          },
        },
        {
          id: 'toast',
          open: async () => {
            await page.getByRole('button', { name: 'Show error' }).click()
            await expect(
              page
                .getByRole('alert')
                .filter({ hasText: 'Synthetic error stayed on screen.' })
            ).toBeVisible()
          },
          close: async () => {
            await page
              .getByRole('button', { name: 'Dismiss Save failed' })
              .click()
          },
        },
      ] as const

      for (const viewport of viewports) {
        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        })
        for (const state of states) {
          await state.open()
          const overflow = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth,
            client: document.documentElement.clientWidth,
          }))
          expect(
            overflow.scroll,
            `${theme} ${viewport.name} ${state.id}`
          ).toBeLessThanOrEqual(overflow.client + 1)

          if (state.id !== 'toast') {
            await page.screenshot({
              path: path.join(
                screenshotDir,
                `${state.id}-${theme}-${viewport.name}.png`
              ),
              fullPage: true,
            })
          }

          const axe = await new AxeBuilder({ page })
            .include('#dialog-showcase')
            .include('#tc-toast-live')
            .analyze()
          writeFileSync(
            path.join(
              evidenceDir,
              `axe-${state.id}-${theme}-${viewport.name}.json`
            ),
            JSON.stringify(
              {
                theme,
                viewport: viewport.width,
                state: state.id,
                violationCount: axe.violations.length,
                violations: axe.violations.map((item) => ({
                  id: item.id,
                  impact: item.impact,
                  help: item.help,
                  nodes: item.nodes.slice(0, 3).map((node) => node.html),
                })),
              },
              null,
              2
            ) + '\n'
          )
          expect(
            axe.violations,
            JSON.stringify(axe.violations, null, 2)
          ).toEqual([])
          await state.close()
        }
      }
    })
  }
})
