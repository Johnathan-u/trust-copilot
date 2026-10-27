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

const evidenceDir = path.resolve(process.cwd(), '../../artifacts/acceptance/TC-14-001')
const screenshotDir = path.join(evidenceDir, 'screenshots')

const viewports = [
  { name: '360', width: 360, height: 800 },
  { name: '768', width: 768, height: 1024 },
  { name: '1440', width: 1440, height: 900 },
] as const

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true })
})

async function openTheme(page: Page, theme: ThemeName) {
  await page.addInitScript((value) => {
    document.documentElement.setAttribute('data-theme', value)
  }, theme)
  await page.goto(`/design-tokens?theme=${theme}`)
  await expect(page.getByTestId('token-showcase')).toHaveAttribute('data-expected-theme', theme)
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
}

test.describe('design tokens', () => {
  test.describe.configure({ timeout: 90_000 })

  for (const theme of themes) {
    test(`${theme} theme renders shared tokens, contrast, focus and has no serious axe violations`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 })
      await openTheme(page, theme)

      const names = Object.keys(themeColors[theme])
      const actual = await page.evaluate((keys) => {
        const style = getComputedStyle(document.documentElement)
        const values: Record<string, string> = {}
        for (const key of keys) values[key] = style.getPropertyValue(key).trim()
        return values
      }, names)
      expect(actual).toEqual(themeColors[theme])

      for (const step of spacingScale) {
        const width = await page.locator(`[data-space="${step.px}"]`).evaluate((el) => getComputedStyle(el).width)
        expect(width, step.cssVar).toBe(`${step.px}px`)
      }

      await expect(page.locator('[data-type="label"]')).toHaveCSS('font-size', '14px')
      await expect(page.locator('[data-type="body"]')).toHaveCSS('font-size', '16px')

      const rendered = await page.locator('[data-contrast-pair]').evaluateAll((nodes) =>
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
      const expectedIds = new Set([...requiredContrastPairs(), disabledContrastPair()].map((entry) => entry.id))
      expect(rendered.map((entry) => entry.id).sort()).toEqual([...expectedIds].sort())
      const contrastFailures = rendered.flatMap((entry) => {
        const ratio = contrastRatio(entry.color, entry.background)
        return ratio + 1e-9 >= entry.min ? [] : [`${entry.id} ${ratio.toFixed(2)} < ${entry.min}`]
      })
      expect(contrastFailures).toEqual([])

      const primary = page.getByTestId('primary-action')
      for (let i = 0; i < 30; i += 1) {
        await page.keyboard.press('Tab')
        if ((await primary.evaluate((el) => el === document.activeElement))) break
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
      expect(contrastRatio(focus.outlineColor, focus.surface)).toBeGreaterThanOrEqual(3)
      expect(contrastRatio(focus.outlineColor, focus.glow)).toBeGreaterThanOrEqual(3)
      expect(focus.top).toBeGreaterThanOrEqual(0)
      expect(focus.bottom).toBeLessThanOrEqual(focus.viewport)

      const transition = await primary.evaluate((el) => getComputedStyle(el).transitionDuration)
      expect(transition).toContain('0.15s')

      for (const viewport of viewports) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height })
        const overflow = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        }))
        expect(overflow.scroll, viewport.name).toBeLessThanOrEqual(overflow.client + 1)

        const axe = await new AxeBuilder({ page }).include('#token-showcase').analyze()
        writeFileSync(
          path.join(evidenceDir, `axe-${theme}-${viewport.name}.json`),
          JSON.stringify(
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
          )
        )
        const blocking = axe.violations.filter((item) => item.impact === 'critical' || item.impact === 'serious')
        expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([])

        await page.screenshot({
          path: path.join(screenshotDir, `theme-${theme}-${viewport.name}.png`),
          fullPage: true,
        })
      }
    })
  }

  test('reduced motion zeroes interaction durations', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openTheme(page, 'dark')
    const duration = await page.getByTestId('primary-action').evaluate((el) => getComputedStyle(el).transitionDuration)
    expect(duration === '0s' || duration.startsWith('0s')).toBe(true)
  })

  test('an unknown theme query keeps the default dark tokens', async ({ page }) => {
    await page.goto('/design-tokens?theme=nope')
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'light')
    const background = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--tc-bg').trim())
    expect(background).toBe(themeColors.dark['--tc-bg'])
    await expect(page.getByTestId('token-showcase')).toHaveAttribute('data-expected-theme', 'dark')
  })
})
