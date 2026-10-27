/**
 * Semantic design tokens for Trust Copilot.
 *
 * Runtime values live in app/globals.css as custom properties. This module is the
 * contract those variables must match, and the list of text/status pairs that
 * have to clear the chosen WCAG 2.2 AA targets.
 *
 * Spacing base unit is 4px. The named scale is 4, 8, 12, 16, 24, 32 and 48.
 */

export const TEXT_CONTRAST_MIN = 4.5
export const NON_TEXT_CONTRAST_MIN = 3

export const themes = ['dark', 'light'] as const
export type ThemeName = (typeof themes)[number]

/** Product spacing scale. Every step is a multiple of the 4px base unit. */
export const spacingScale = [
  { step: 1, px: 4, cssVar: '--tc-space-1' },
  { step: 2, px: 8, cssVar: '--tc-space-2' },
  { step: 3, px: 12, cssVar: '--tc-space-3' },
  { step: 4, px: 16, cssVar: '--tc-space-4' },
  { step: 6, px: 24, cssVar: '--tc-space-6' },
  { step: 8, px: 32, cssVar: '--tc-space-8' },
  { step: 12, px: 48, cssVar: '--tc-space-12' },
] as const

export const spacingBasePx = 4

/** System faces used when the self-hosted Inter file is not applied. */
export const systemFontFallback = [
  'ui-sans-serif',
  'system-ui',
  '-apple-system',
  'BlinkMacSystemFont',
  '"Segoe UI"',
  'sans-serif',
] as const

export const typography = {
  /**
   * `--font-inter` is set by next/font/local from the bundled Inter files.
   * The fallback inside var() and the rest of the stack are system fonts.
   */
  fontSans: `var(--font-inter, ui-sans-serif), ${systemFontFallback.join(', ')}`,
  caption: {
    size: 12,
    line: 16,
    cssSize: '--tc-font-size-caption',
    cssLine: '--tc-line-caption',
  },
  label: {
    size: 14,
    line: 20,
    cssSize: '--tc-font-size-label',
    cssLine: '--tc-line-label',
  },
  body: {
    size: 16,
    line: 24,
    cssSize: '--tc-font-size-body',
    cssLine: '--tc-line-body',
  },
  title: {
    size: 20,
    line: 28,
    cssSize: '--tc-font-size-title',
    cssLine: '--tc-line-title',
  },
  headline: {
    size: 28,
    line: 36,
    cssSize: '--tc-font-size-headline',
    cssLine: '--tc-line-headline',
  },
} as const

export const interaction = {
  focusWidth: '2px',
  focusOffset: '2px',
  durationFast: '150ms',
  durationNormal: '200ms',
  ease: 'cubic-bezier(0.2, 0, 0, 1)',
  /** WCAG 2.2 SC 2.5.8 AA target size. */
  targetMin: '24px',
  radiusCard: '18px',
  radiusControl: '12px',
  radiusXs: '8px',
} as const

/**
 * Decorative dark-theme washes. Alphas are low enough that text tokens still
 * clear 4.5:1 on the lightest composited pixel. See docs/design/tokens.md.
 */
export const darkDecorative = {
  baseTop: '#09111f',
  baseBottom: '#070d18',
  primaryGlow: '#5b7cff',
  primaryGlowAlpha: 0.08,
  successGlow: '#10b981',
  successGlowAlpha: 0.06,
  panel: '#0c1526',
  panelAlpha: 0.82,
} as const

const darkColors = {
  '--tc-bg': '#08111f',
  '--tc-surface': '#08111f',
  '--tc-surface-raised': '#10192c',
  '--tc-surface-sunken': '#070d18',
  '--tc-surface-overlay': '#0c1526',
  '--tc-surface-glow-primary': '#101a31',
  '--tc-surface-glow-success': '#091b25',
  '--tc-panel': 'rgba(12, 21, 38, 0.82)',
  '--tc-panel-2': '#10192c',
  '--tc-panel-3': 'rgba(10, 18, 33, 0.72)',
  '--tc-sidebar': '#0b1220',
  '--tc-border': 'rgba(255, 255, 255, 0.09)',
  '--tc-border-strong': '#8b9bb4',
  '--tc-text': '#e8eefb',
  '--tc-muted': '#94a3b8',
  '--tc-soft': '#c7d2fe',
  '--tc-primary': '#5b7cff',
  '--tc-primary-2': '#7c96ff',
  '--tc-primary-solid': '#3e4ec0',
  '--tc-primary-solid-hover': '#2f3fa3',
  '--tc-on-primary': '#ffffff',
  '--tc-focus': '#7c96ff',
  '--tc-success': '#22c55e',
  '--tc-success-surface': '#12352a',
  '--tc-warning': '#f59e0b',
  '--tc-warning-surface': '#352e27',
  '--tc-danger': '#ef4444',
  '--tc-danger-surface': '#1a1828',
  '--tc-danger-solid': '#b91c1c',
  '--tc-danger-solid-hover': '#7f1d1d',
  '--tc-on-danger': '#ffffff',
  '--tc-info': '#c7d2fe',
  '--tc-info-surface': '#1a2140',
  '--tc-disabled-fg': '#6b778c',
  '--tc-disabled-bg': '#1a2436',
  '--tc-disabled-border': '#6e7e96',
  '--tc-nav-active-bg': '#1c2748',
  '--tc-nav-active-border': '#5b7cff',
  '--tc-hover': 'rgba(255, 255, 255, 0.06)',
  '--tc-overlay': 'rgba(0, 0, 0, 0.5)',
  '--tc-chip': '#1a2140',
  '--tc-grid': 'rgba(255, 255, 255, 0.03)',
  '--tc-shadow': '0 20px 60px rgba(0, 0, 0, 0.35)',
  '--tc-brand-mark': '#3e4ec0',
  '--tc-brand-mark-shadow': '0 12px 30px rgba(62, 78, 192, 0.35)',
  '--tc-body-background':
    'radial-gradient(circle at top left, rgba(91, 124, 255, 0.08), transparent 28%), radial-gradient(circle at 85% 10%, rgba(16, 185, 129, 0.06), transparent 22%), linear-gradient(180deg, #09111f 0%, #070d18 100%)',
} as const

const lightColors = {
  '--tc-bg': '#f8fafc',
  '--tc-surface': '#f8fafc',
  '--tc-surface-raised': '#ffffff',
  '--tc-surface-sunken': '#f1f5f9',
  '--tc-surface-overlay': '#ffffff',
  '--tc-surface-glow-primary': '#ffffff',
  '--tc-surface-glow-success': '#ffffff',
  '--tc-panel': '#ffffff',
  '--tc-panel-2': '#f1f5f9',
  '--tc-panel-3': '#f8fafc',
  '--tc-sidebar': '#ffffff',
  '--tc-border': '#cbd5e1',
  '--tc-border-strong': '#64748b',
  '--tc-text': '#0f172a',
  '--tc-muted': '#334155',
  '--tc-soft': '#1e293b',
  '--tc-primary': '#0f766e',
  '--tc-primary-2': '#0f766e',
  '--tc-primary-solid': '#0f766e',
  '--tc-primary-solid-hover': '#115e59',
  '--tc-on-primary': '#ffffff',
  '--tc-focus': '#0f766e',
  '--tc-success': '#166534',
  '--tc-success-surface': '#dcfce7',
  '--tc-warning': '#92400e',
  '--tc-warning-surface': '#fffbeb',
  '--tc-danger': '#991b1b',
  '--tc-danger-surface': '#fee2e2',
  '--tc-danger-solid': '#991b1b',
  '--tc-danger-solid-hover': '#7f1d1d',
  '--tc-on-danger': '#ffffff',
  '--tc-info': '#1e40af',
  '--tc-info-surface': '#dbeafe',
  '--tc-disabled-fg': '#64748b',
  '--tc-disabled-bg': '#e2e8f0',
  '--tc-disabled-border': '#64748b',
  '--tc-nav-active-bg': '#ccfbf1',
  '--tc-nav-active-border': '#0f766e',
  '--tc-hover': 'rgba(15, 23, 42, 0.06)',
  '--tc-overlay': 'rgba(15, 23, 42, 0.45)',
  '--tc-chip': '#dbeafe',
  '--tc-grid': 'rgba(15, 23, 42, 0.04)',
  '--tc-shadow': '0 12px 32px rgba(15, 23, 42, 0.08)',
  '--tc-brand-mark': '#0f766e',
  '--tc-brand-mark-shadow': '0 12px 30px rgba(15, 118, 110, 0.25)',
  '--tc-body-background': '#f8fafc',
} as const

export const themeColors: Record<ThemeName, Record<string, string>> = {
  dark: darkColors,
  light: lightColors,
}

export const rootSharedTokens: Record<string, string> = {
  '--tc-font-sans': typography.fontSans,
  '--tc-font-size-caption': `${typography.caption.size}px`,
  '--tc-line-caption': `${typography.caption.line}px`,
  '--tc-font-size-label': `${typography.label.size}px`,
  '--tc-line-label': `${typography.label.line}px`,
  '--tc-font-size-body': `${typography.body.size}px`,
  '--tc-line-body': `${typography.body.line}px`,
  '--tc-font-size-title': `${typography.title.size}px`,
  '--tc-line-title': `${typography.title.line}px`,
  '--tc-font-size-headline': `${typography.headline.size}px`,
  '--tc-line-headline': `${typography.headline.line}px`,
  '--tc-weight-regular': '400',
  '--tc-weight-medium': '500',
  '--tc-weight-semibold': '600',
  '--tc-weight-bold': '700',
  '--tc-space-1': '4px',
  '--tc-space-2': '8px',
  '--tc-space-3': '12px',
  '--tc-space-4': '16px',
  '--tc-space-6': '24px',
  '--tc-space-8': '32px',
  '--tc-space-12': '48px',
  '--tc-radius': interaction.radiusCard,
  '--tc-radius-sm': interaction.radiusControl,
  '--tc-radius-xs': interaction.radiusXs,
  '--tc-focus-width': interaction.focusWidth,
  '--tc-focus-offset': interaction.focusOffset,
  '--tc-duration-fast': interaction.durationFast,
  '--tc-duration-normal': interaction.durationNormal,
  '--tc-ease': interaction.ease,
  '--tc-target-min': interaction.targetMin,
}

/** Neutral surfaces body, muted, link and status text must clear. */
export const neutralSurfaces = [
  '--tc-bg',
  '--tc-surface-raised',
  '--tc-surface-sunken',
  '--tc-surface-overlay',
  '--tc-surface-glow-primary',
  '--tc-surface-glow-success',
  '--tc-sidebar',
  '--tc-panel-2',
] as const

/** Text and status foregrounds. Filled controls use the on-* tokens instead. */
export const textRoles = [
  '--tc-text',
  '--tc-muted',
  '--tc-soft',
  '--tc-primary',
  '--tc-primary-2',
  '--tc-success',
  '--tc-warning',
  '--tc-danger',
  '--tc-info',
] as const

export const statusSurfacePairs = [
  ['--tc-success', '--tc-success-surface'],
  ['--tc-warning', '--tc-warning-surface'],
  ['--tc-danger', '--tc-danger-surface'],
  ['--tc-info', '--tc-info-surface'],
] as const

export const fillPairs = [
  ['--tc-on-primary', '--tc-primary-solid'],
  ['--tc-on-primary', '--tc-primary-solid-hover'],
  ['--tc-on-danger', '--tc-danger-solid'],
  ['--tc-on-danger', '--tc-danger-solid-hover'],
] as const

export const nonTextRoles = ['--tc-focus', '--tc-border-strong'] as const

export type ContrastKind = 'text' | 'nontext' | 'disabled'

export interface ContrastPair {
  id: string
  fg: string
  bg: string
  min: number
  kind: ContrastKind
}

export function tokenSlug(cssVar: string): string {
  return cssVar.replace(/^--tc-/, '')
}

export function contrastPairId(fg: string, bg: string): string {
  return `${tokenSlug(fg)}-on-${tokenSlug(bg)}`
}

function pair(
  fg: string,
  bg: string,
  min: number,
  kind: ContrastKind
): ContrastPair {
  return { id: contrastPairId(fg, bg), fg, bg, min, kind }
}

/** Active text, status and non-text pairs. Disabled is returned separately. */
export function requiredContrastPairs(): ContrastPair[] {
  const pairs: ContrastPair[] = []
  for (const fg of textRoles) {
    for (const bg of neutralSurfaces) {
      pairs.push(pair(fg, bg, TEXT_CONTRAST_MIN, 'text'))
    }
  }
  for (const [fg, bg] of statusSurfacePairs) {
    pairs.push(pair(fg, bg, TEXT_CONTRAST_MIN, 'text'))
  }
  for (const [fg, bg] of fillPairs) {
    pairs.push(pair(fg, bg, TEXT_CONTRAST_MIN, 'text'))
  }
  pairs.push(pair('--tc-text', '--tc-nav-active-bg', TEXT_CONTRAST_MIN, 'text'))
  for (const fg of nonTextRoles) {
    for (const bg of neutralSurfaces) {
      pairs.push(pair(fg, bg, NON_TEXT_CONTRAST_MIN, 'nontext'))
    }
  }
  pairs.push(
    pair(
      '--tc-nav-active-border',
      '--tc-nav-active-bg',
      NON_TEXT_CONTRAST_MIN,
      'nontext'
    )
  )
  pairs.push(
    pair(
      '--tc-nav-active-border',
      '--tc-sidebar',
      NON_TEXT_CONTRAST_MIN,
      'nontext'
    )
  )
  pairs.push(
    pair(
      '--tc-disabled-border',
      '--tc-disabled-bg',
      NON_TEXT_CONTRAST_MIN,
      'nontext'
    )
  )
  return pairs
}

/**
 * Disabled text is an inactive component, so WCAG 1.4.3 does not require 4.5:1.
 * The token still has to stay visible against its disabled surface (3:1).
 */
export function disabledContrastPair(): ContrastPair {
  return pair(
    '--tc-disabled-fg',
    '--tc-disabled-bg',
    NON_TEXT_CONTRAST_MIN,
    'disabled'
  )
}

export function isHexColor(value: string): boolean {
  return /^#[0-9a-fA-F]{6}$/.test(value)
}
