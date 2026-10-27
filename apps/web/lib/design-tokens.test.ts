import { readFileSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'
import { compositeHex, contrastRatio, meetsContrast } from './contrast'
import {
  TEXT_CONTRAST_MIN,
  darkDecorative,
  disabledContrastPair,
  requiredContrastPairs,
  rootSharedTokens,
  spacingBasePx,
  spacingScale,
  themeColors,
} from './design-tokens'
import { formatApiErrorDetail, apiErrorPresentation, API_ERROR_STATUS } from './api-error'

function readCssBlock(css: string, header: string): Record<string, string> {
  const marker = `/* ${header} */`
  const start = css.indexOf(marker)
  if (start < 0) throw new Error(`missing CSS marker ${header}`)
  const brace = css.indexOf('{', start)
  let depth = 0
  let end = brace
  for (let i = brace; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1
    else if (css[i] === '}') {
      depth -= 1
      if (depth === 0) {
        end = i
        break
      }
    }
  }
  const body = css.slice(brace + 1, end)
  const vars: Record<string, string> = {}
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi
  for (const match of body.matchAll(re)) {
    vars[match[1]] = match[2].trim()
  }
  return vars
}

const css = readFileSync(path.join(process.cwd(), 'app/globals.css'), 'utf8')
const rootVars = readCssBlock(css, 'tc-tokens:dark')
const lightVars = readCssBlock(css, 'tc-tokens:light')

describe('design token contract', () => {
  it('documents a 4px spacing scale of 4, 8, 12, 16, 24, 32 and 48', () => {
    expect(spacingScale.map((step) => step.px)).toEqual([4, 8, 12, 16, 24, 32, 48])
    for (const step of spacingScale) {
      expect(step.px % spacingBasePx).toBe(0)
      expect(rootSharedTokens[step.cssVar]).toBe(`${step.px}px`)
      expect(rootVars[step.cssVar]).toBe(`${step.px}px`)
    }
  })

  it('keeps typography and interaction tokens in the dark root and out of the light override', () => {
    for (const [name, value] of Object.entries(rootSharedTokens)) {
      expect(rootVars[name], name).toBe(value)
      expect(lightVars[name], name).toBeUndefined()
    }
  })

  it('matches semantic color variables for the dark and light themes', () => {
    for (const [name, value] of Object.entries(themeColors.dark)) {
      expect(rootVars[name], name).toBe(value)
    }
    for (const [name, value] of Object.entries(themeColors.light)) {
      expect(lightVars[name], name).toBe(value)
    }
  })

  it('derives decorative glow surfaces from the published alphas', () => {
    expect(
      compositeHex(darkDecorative.primaryGlow, darkDecorative.baseTop, darkDecorative.primaryGlowAlpha)
    ).toBe(themeColors.dark['--tc-surface-glow-primary'])
    expect(
      compositeHex(darkDecorative.successGlow, darkDecorative.baseTop, darkDecorative.successGlowAlpha)
    ).toBe(themeColors.dark['--tc-surface-glow-success'])
    expect(rootVars['--tc-body-background']).toContain('rgba(91, 124, 255, 0.08)')
    expect(rootVars['--tc-body-background']).toContain('rgba(16, 185, 129, 0.06)')
  })
})

describe('WCAG 2.2 AA contrast targets', () => {
  it.each(['dark', 'light'] as const)('%s theme text, status, fill and non-text pairs meet their targets', (theme) => {
    const colors = themeColors[theme]
    const failures: string[] = []
    for (const entry of requiredContrastPairs()) {
      const fg = colors[entry.fg]
      const bg = colors[entry.bg]
      if (!fg?.startsWith('#') || !bg?.startsWith('#')) {
        failures.push(`${entry.id} is not an opaque hex pair (${fg} on ${bg})`)
        continue
      }
      if (!meetsContrast(fg, bg, entry.min)) {
        failures.push(`${entry.id} ${contrastRatio(fg, bg).toFixed(2)} < ${entry.min}`)
      }
    }
    expect(failures).toEqual([])
  })

  it('keeps disabled text visible without treating it as an active 4.5:1 pair', () => {
    const disabled = disabledContrastPair()
    expect(disabled.min).toBe(3)
    expect(disabled.kind).toBe('disabled')
    for (const theme of ['dark', 'light'] as const) {
      const fg = themeColors[theme][disabled.fg]
      const bg = themeColors[theme][disabled.bg]
      expect(meetsContrast(fg, bg, 3)).toBe(true)
    }
    const activeIds = new Set(requiredContrastPairs().filter((entry) => entry.kind === 'text').map((entry) => entry.id))
    expect(activeIds.has(disabled.id)).toBe(false)
  })

  it('rejects a known failing combination so the guard is not vacuous', () => {
    expect(meetsContrast('#ffffff', themeColors.light['--tc-bg'], TEXT_CONTRAST_MIN)).toBe(false)
    expect(meetsContrast('#ffffff', themeColors.dark['--tc-primary'], TEXT_CONTRAST_MIN)).toBe(false)
  })

  it('keeps text tokens at 4.5:1 on the translucent dark panel over each glow', () => {
    const textOnPanel = ['--tc-text', '--tc-muted', '--tc-primary', '--tc-danger', '--tc-success', '--tc-warning']
    const glows = [themeColors.dark['--tc-surface-glow-primary'], themeColors.dark['--tc-surface-glow-success']]
    for (const glow of glows) {
      const panel = compositeHex(darkDecorative.panel, glow, darkDecorative.panelAlpha)
      for (const token of textOnPanel) {
        const fg = themeColors.dark[token]
        expect(meetsContrast(fg, panel, TEXT_CONTRAST_MIN), `${token} on ${panel}`).toBe(true)
      }
    }
  })
})

describe('API error presentation', () => {
  it('returns a string detail unchanged', () => {
    expect(formatApiErrorDetail({ detail: 'Workspace name is already taken' })).toBe(
      'Workspace name is already taken'
    )
  })

  it('uses the first validation message and ignores unrelated fields', () => {
    const body = {
      detail: [{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }],
      password: 'not-a-real-secret',
      token: 'synthetic-token',
    }
    expect(formatApiErrorDetail(body)).toBe('Field required')
    expect(formatApiErrorDetail(body)).not.toContain('synthetic-token')
    expect(formatApiErrorDetail(body)).not.toContain('not-a-real-secret')
  })

  it('reads an object detail message and falls back otherwise', () => {
    expect(formatApiErrorDetail({ detail: { msg: 'Not allowed' } })).toBe('Not allowed')
    expect(formatApiErrorDetail(null)).toBe('Request failed')
    expect(formatApiErrorDetail('nope')).toBe('Request failed')
    expect(formatApiErrorDetail({})).toBe('Request failed')
  })

  it('maps every failure and denial to the danger status token', () => {
    expect(API_ERROR_STATUS).toBe('danger')
    expect(apiErrorPresentation({ detail: 'Not allowed' })).toEqual({
      message: 'Not allowed',
      status: 'danger',
    })
    expect(apiErrorPresentation(undefined, 'Network error. Please try again.')).toEqual({
      message: 'Network error. Please try again.',
      status: 'danger',
    })
  })
})
