import { readdirSync, readFileSync, statSync } from 'fs'
import path from 'path'
import { describe, expect, it } from 'vitest'
import { systemFontFallback, typography } from '@/lib/design-tokens'

const repoRoot = path.resolve(process.cwd(), '..')
const webRoot = process.cwd()
const fontDir = path.join(webRoot, 'app/fonts')

const forbidden = [
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'next/font/google',
]
const skipDirs = new Set([
  'node_modules',
  '.next',
  '.git',
  'dist',
  'coverage',
  'test-results',
  'playwright-report',
  'docs',
  'artifacts',
])
const textExt = new Set([
  '.ts',
  '.tsx',
  '.js',
  '.jsx',
  '.css',
  '.html',
  '.mjs',
  '.cjs',
])

function collectTextFiles(dir: string, out: string[]) {
  for (const name of readdirSync(dir)) {
    if (skipDirs.has(name)) continue
    const full = path.join(dir, name)
    const info = statSync(full)
    if (info.isDirectory()) {
      collectTextFiles(full, out)
      continue
    }
    if (!textExt.has(path.extname(name))) continue
    if (name.endsWith('.test.ts') || name.endsWith('.spec.ts')) continue
    out.push(full)
  }
}

describe('self-hosted Inter', () => {
  it('bundles the OFL variable files and does not name a third-party font host in shipped source', () => {
    const license = readFileSync(path.join(fontDir, 'LICENSE.txt'), 'utf8')
    expect(license).toContain('SIL Open Font License, Version 1.1')
    expect(license).toContain('Copyright (c) 2016 The Inter Project Authors')
    for (const file of ['InterVariable.woff2', 'InterVariable-Italic.woff2']) {
      const bytes = readFileSync(path.join(fontDir, file))
      expect(bytes.subarray(0, 4).toString('ascii'), file).toBe('wOF2')
      expect(bytes.length, file).toBeGreaterThan(10_000)
    }

    const layout = readFileSync(path.join(webRoot, 'app/layout.tsx'), 'utf8')
    expect(layout).toContain("from 'next/font/local'")
    expect(layout).not.toContain('next/font/google')
    expect(layout).toContain('./fonts/InterVariable.woff2')
    expect(layout).toContain('./fonts/InterVariable-Italic.woff2')

    const files: string[] = []
    collectTextFiles(repoRoot, files)
    const hits = files.flatMap((file) => {
      const text = readFileSync(file, 'utf8')
      return forbidden
        .filter((needle) => text.includes(needle))
        .map((needle) => `${file} contains ${needle}`)
    })
    expect(hits).toEqual([])
  })

  it('keeps a system-font fallback behind the self-hosted family', () => {
    expect(
      typography.fontSans.startsWith('var(--font-inter, ui-sans-serif)')
    ).toBe(true)
    for (const face of systemFontFallback) {
      expect(typography.fontSans).toContain(face)
    }
    expect(typography.fontSans).not.toContain('fonts.googleapis.com')
  })
})
