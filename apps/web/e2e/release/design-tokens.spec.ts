import { mkdirSync, writeFileSync } from 'fs'
import path from 'path'
import { expect, test, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { contrastRatio } from '../../lib/contrast'
import {
  disabledContrastPair,
  requiredContrastPairs,
  spacingScale,
  themeColors,
  themes,
  type ThemeName,
} from '../../lib/design-tokens'

const evidenceDir = path.resolve(
  process.cwd(),
  '../../artifacts/acceptance/TC-14-001'
)
const screenshotDir = path.join(evidenceDir, 'screenshots')

const viewports = [
  { name: '360', width: 360, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '1440', width: 1440, height: 900 },
] as const

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

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

/** Chrome serializes custom properties (#rrggbbaa, #fff). Compare the same color. */
function canonicalTokenValue(value: string): string {
  return value.replace(
    /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b|rgba?\([^)]*\)/g,
    (match) => {
      const parsed = parseCssColor(match)
      return parsed
        ? `rgba(${parsed[0]},${parsed[1]},${parsed[2]},${parsed[3]})`
        : match
    }
  )
}

function parseCssColor(input: string): [number, number, number, number] | null {
  const hex = input.trim().match(/^#([0-9a-fA-F]{3,8})$/)
  if (hex) {
    let body = hex[1]
    if (body.length === 3 || body.length === 4) {
      body = body
        .split('')
        .map((char) => char + char)
        .join('')
    }
    const value = Number.parseInt(body, 16)
    if (body.length === 6) {
      return [(value >> 16) & 255, (value >> 8) & 255, value & 255, 255]
    }
    if (body.length === 8) {
      return [
        (value >> 24) & 255,
        (value >> 16) & 255,
        (value >> 8) & 255,
        value & 255,
      ]
    }
  }
  const rgb = input.match(
    /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/i
  )
  if (!rgb) return null
  const alpha = rgb[4] === undefined ? 255 : Math.round(Number(rgb[4]) * 255)
  return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3]), alpha]
}

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

async function openTheme(page: Page, theme: ThemeName) {
  await page.addInitScript((value) => {
    document.documentElement.setAttribute('data-theme', value)
  }, theme)
  await page.goto(`/design-tokens?theme=${theme}`)
  await expect(page.getByTestId('token-showcase')).toHaveAttribute(
    'data-expected-theme',
    theme
  )
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
}

test.describe('design tokens', () => {
  test.describe.configure({ timeout: 90_000 })

  for (const theme of themes) {
    test(`${theme} theme renders shared tokens, contrast, focus and has no serious axe violations`, async ({
      page,
    }) => {
      const requests = watchRequests(page)
      await page.setViewportSize({ width: 1440, height: 900 })
      await openTheme(page, theme)
      assertSelfHostedFonts(page.url(), requests)
      const font = await page.evaluate(async () => {
        await document.fonts.ready
        return {
          family: getComputedStyle(document.body).fontFamily,
          token: getComputedStyle(document.documentElement).getPropertyValue(
            '--tc-font-sans'
          ),
        }
      })
      expect(font.family.toLowerCase()).toContain('inter')
      expect(font.token).toContain('ui-sans-serif')
      expect(font.token).toContain('system-ui')

      const names = Object.keys(themeColors[theme])
      const actual = await page.evaluate((keys) => {
        const style = getComputedStyle(document.documentElement)
        const values: Record<string, string> = {}
        for (const key of keys) values[key] = style.getPropertyValue(key).trim()
        return values
      }, names)
      const mismatches = names.flatMap((name) => {
        const expected = canonicalTokenValue(themeColors[theme][name])
        const received = canonicalTokenValue(actual[name])
        return expected === received
          ? []
          : [`${name}: ${received} != ${expected}`]
      })
      expect(mismatches).toEqual([])

      for (const step of spacingScale) {
        const width = await page
          .locator(`[data-space="${step.px}"]`)
          .evaluate((el) => getComputedStyle(el).width)
        expect(width, step.cssVar).toBe(`${step.px}px`)
      }

      await expect(page.locator('[data-type="label"]')).toHaveCSS(
        'font-size',
        '14px'
      )
      await expect(page.locator('[data-type="body"]')).toHaveCSS(
        'font-size',
        '16px'
      )

      const rendered = await page
        .locator('[data-contrast-pair]')
        .evaluateAll((nodes) =>
          nodes.map((node) => {
            const style = getComputedStyle(node)
            return {
              id: node.getAttribute('data-contrast-pair'),
              min: Number(node.getAttribute('data-min')),
              color: style.color,
              background: style.backgroundColor,
            }
          })
        )
      const expectedIds = new Set(
        [...requiredContrastPairs(), disabledContrastPair()].map(
          (entry) => entry.id
        )
      )
      expect(rendered.map((entry) => entry.id).sort()).toEqual(
        [...expectedIds].sort()
      )
      const contrastFailures = rendered.flatMap((entry) => {
        const ratio = contrastRatio(entry.color, entry.background)
        return ratio + 1e-9 >= entry.min
          ? []
          : [`${entry.id} ${ratio.toFixed(2)} < ${entry.min}`]
      })
      expect(contrastFailures).toEqual([])

      const primary = page.getByTestId('primary-action')
      for (let i = 0; i < 30; i += 1) {
        await page.keyboard.press('Tab')
        if (await primary.evaluate((el) => el === document.activeElement)) break
      }
      await expect(primary).toBeFocused()
      const focus = await primary.evaluate((el) => {
        const style = getComputedStyle(el)
        const root = getComputedStyle(document.documentElement)
        const box = el.getBoundingClientRect()
        return {
          outlineStyle: style.outlineStyle,
          outlineWidth: style.outlineWidth,
          outlineColor: style.outlineColor,
          surface: root.getPropertyValue('--tc-bg').trim(),
          glow: root.getPropertyValue('--tc-surface-glow-primary').trim(),
          top: box.top,
          bottom: box.bottom,
          viewport: window.innerHeight,
        }
      })
      expect(focus.outlineStyle).not.toBe('none')
      expect(parseFloat(focus.outlineWidth)).toBeGreaterThanOrEqual(2)
      expect(
        contrastRatio(focus.outlineColor, focus.surface)
      ).toBeGreaterThanOrEqual(3)
      expect(
        contrastRatio(focus.outlineColor, focus.glow)
      ).toBeGreaterThanOrEqual(3)
      expect(focus.top).toBeGreaterThanOrEqual(0)
      expect(focus.bottom).toBeLessThanOrEqual(focus.viewport)

      const transition = await primary.evaluate(
        (el) => getComputedStyle(el).transitionDuration
      )
      expect(transition).toContain('0.15s')

      for (const viewport of viewports) {
        await page.setViewportSize({
          width: viewport.width,
          height: viewport.height,
        })
        const overflow = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }))
        expect(overflow.scroll, viewport.name).toBeLessThanOrEqual(
          overflow.client + 1
        )

        const axe = await new AxeBuilder({ page })
          .include('#token-showcase')
          .analyze()
        writeFileSync(
          path.join(evidenceDir, `axe-${theme}-${viewport.name}.json`),
          `${JSON.stringify(
            {
              theme,
              viewport: viewport.width,
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
        const blocking = axe.violations.filter(
          (item) => item.impact === 'critical' || item.impact === 'serious'
        )
        expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([])

        await page.screenshot({
          path: path.join(screenshotDir, `theme-${theme}-${viewport.name}.png`),
          fullPage: true,
        })
      }
    })
  }

  test('reduced motion zeroes interaction durations', async ({ page }) => {
    const requests = watchRequests(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openTheme(page, 'dark')
    assertSelfHostedFonts(page.url(), requests)
    const duration = await page
      .getByTestId('primary-action')
      .evaluate((el) => getComputedStyle(el).transitionDuration)
    expect(duration === '0s' || duration.startsWith('0s')).toBe(true)
  })

  test('an unknown theme query keeps the default dark tokens', async ({
    page,
  }) => {
    const requests = watchRequests(page)
    await page.goto('/design-tokens?theme=nope')
    assertSelfHostedFonts(page.url(), requests)
    await expect(page.locator('html')).not.toHaveAttribute(
      'data-theme',
      'light'
    )
    const background = await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue('--tc-bg')
        .trim()
    )
    expect(background).toBe(themeColors.dark['--tc-bg'])
    await expect(page.getByTestId('token-showcase')).toHaveAttribute(
      'data-expected-theme',
      'dark'
    )
  })
})
