import { readdirSync, readFileSync, statSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'

/**
 * Shared UI, the dashboard, the shell layout, and the rest of app/ and
 * components/ must use --tc-* tokens. A raw Tailwind palette class or an
 * rgb/rgba/hsl/hex colour in those trees fails this test.
 * app/globals.css is the token definition file and stays outside the gate.
 */
const webRoot = process.cwd()
const uiDir = path.join(webRoot, 'components/ui')
const dashboardDir = path.join(webRoot, 'app/dashboard')
const layoutDir = path.join(webRoot, 'components/layout')
const appDir = path.join(webRoot, 'app')
const componentsDir = path.join(webRoot, 'components')

/** Token definitions. Raw colours here are the palette, not a consumer. */
const tokenDefinitions = new Set(
  [path.join(appDir, 'globals.css')].map((file) => path.normalize(file))
)

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
    if (tokenDefinitions.has(path.normalize(full))) continue
    if (/\.(tsx|ts|css)$/.test(name)) out.push(full)
  }
  return out
}

function directoryHits(
  label: string,
  dir: string
): { hits: string[]; summary: string } {
  const perFile = new Map<string, number>()
  const hits: string[] = []
  for (const file of sourceFiles(dir)) {
    const fileHits = rawPaletteHits(readFileSync(file, 'utf8'))
    if (fileHits.length === 0) continue
    const rel = path.relative(dir, file)
    perFile.set(rel, fileHits.length)
    for (const hit of fileHits) hits.push(`${rel} ${hit}`)
  }
  const lines = [...perFile.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([file, count]) => `${count} ${file}`)
  const summary = [
    `${label} hits=${hits.length} files=${perFile.size}`,
    ...lines,
  ].join('\n')
  return { hits, summary }
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

describe('dashboard and layout raw colours', () => {
  it('keeps raw palette classes and hex/rgb colours out of app/dashboard', () => {
    const { hits, summary } = directoryHits(
      'apps/web/app/dashboard',
      dashboardDir
    )
    expect(hits, summary).toEqual([])
  })

  it('keeps raw palette classes and hex/rgb colours out of components/layout', () => {
    const { hits, summary } = directoryHits(
      'apps/web/components/layout',
      layoutDir
    )
    expect(hits, summary).toEqual([])
  })
})

describe('app and components raw colours', () => {
  it('keeps raw palette classes and hex/rgb colours out of app and components, except token definitions', () => {
    const app = directoryHits('apps/web/app', appDir)
    const components = directoryHits('apps/web/components', componentsDir)
    const hits = [...app.hits, ...components.hits]
    const summary = [app.summary, components.summary].join('\n')
    expect(hits, summary).toEqual([])
  })
})
