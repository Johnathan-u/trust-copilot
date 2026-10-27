/** WCAG 2.x relative luminance and contrast. Pure functions, no DOM. */

export interface Rgb {
  r: number
  g: number
  b: number
}

export function parseHex(input: string): Rgb {
  const hex = input.trim().replace('#', '')
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) {
    throw new Error(`Expected a 6-digit hex color, received ${input}`)
  }
  return {
    r: parseInt(hex.slice(0, 2), 16),
    g: parseInt(hex.slice(2, 4), 16),
    b: parseInt(hex.slice(4, 6), 16),
  }
}

/** Accepts #rrggbb or the rgb()/rgba() form returned by getComputedStyle. */
export function parseCssColor(input: string): Rgb {
  const value = input.trim()
  if (value.startsWith('#')) return parseHex(value)
  const match = value.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/i)
  if (!match) throw new Error(`Unsupported CSS color ${input}`)
  return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) }
}

function channel(c: number): number {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

export function relativeLuminance(color: string): number {
  const { r, g, b } = parseCssColor(color)
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

/** WCAG contrast ratio, 1 to 21. */
export function contrastRatio(foreground: string, background: string): number {
  const l1 = relativeLuminance(foreground)
  const l2 = relativeLuminance(background)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}

export function meetsContrast(foreground: string, background: string, minimum: number): boolean {
  return contrastRatio(foreground, background) + 1e-9 >= minimum
}

/** Source-over composite of a hex color at `alpha` onto an opaque hex background. */
export function compositeHex(foreground: string, background: string, alpha: number): string {
  if (alpha < 0 || alpha > 1) throw new Error(`Alpha out of range: ${alpha}`)
  const fg = parseHex(foreground)
  const bg = parseHex(background)
  const mix = (a: number, b: number) => Math.round(a * alpha + b * (1 - alpha))
  const toHex = (n: number) => n.toString(16).padStart(2, '0')
  return `#${toHex(mix(fg.r, bg.r))}${toHex(mix(fg.g, bg.g))}${toHex(mix(fg.b, bg.b))}`
}
