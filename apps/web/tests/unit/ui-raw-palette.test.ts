import { readdirSync, readFileSync, statSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'

/**
 * Shared UI must use --tc-* tokens. A raw Tailwind palette class or an
 * rgb/rgba/hsl/hex colour in components/ui fails this test.
 */
const uiDir = path.join(process.cwd(), 'components/ui')

const paletteClass =
  /(?<![A-Za-z0-9_-])(?:[A-Za-z-]+:)*?(?:bg|text|border|divide|ring|outline|from|to|via|fill|stroke|placeholder|decoration|accent|caret|shadow)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d{2,3})?(?:\/\d{1,3})?(?![A-Za-z0-9_-])/g

const rawColor =
  /(?:rgba?|hsla?)\([^)]*\)|#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g

function rawPaletteHits(source: string): string[] {
  const hits: string[] = []
  const lines = source.split('\n')
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    for (const pattern of [paletteClass, rawColor]) {
      pattern.lastIndex = 0
      for (const match of line.matchAll(pattern)) {
        hits.push(`${index + 1}: ${match[0].trim()}`)
      }
    }
  }
  return hits
}

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full))
      continue
    }
    if (/\.(tsx|ts|css)$/.test(name)) out.push(full)
  }
  return out
}

describe('components/ui raw colours', () => {
  it('flags palette classes and rgba colours, and allows token utilities', () => {
    expect(rawPaletteHits('bg-white/5')).toEqual(['1: bg-white/5'])
    expect(rawPaletteHits('hover:bg-white/10')).toEqual([
      '1: hover:bg-white/10',
    ])
    expect(rawPaletteHits('divide-white/10')).toEqual(['1: divide-white/10'])
    expect(rawPaletteHits('border-[rgba(91,124,255,0.4)]')).toEqual([
      '1: rgba(91,124,255,0.4)',
    ])
    expect(rawPaletteHits('bg-[#5b7cff]')).toEqual(['1: #5b7cff'])
    expect(
      rawPaletteHits(
        'bg-tc-surface-sunken border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)] hover:bg-[var(--tc-hover)] divide-tc-border text-tc-text'
      )
    ).toEqual([])
  })

  it('keeps raw palette classes and rgba colours out of components/ui', () => {
    const hits = sourceFiles(uiDir).flatMap((file) =>
      rawPaletteHits(readFileSync(file, 'utf8')).map(
        (hit) => `${path.relative(uiDir, file)} ${hit}`
      )
    )
    expect(hits).toEqual([])
  })
})
