import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  FRAMEWORK_OPTIONS,
  SUBJECT_AREA_OPTIONS,
  formatCreatedAt,
  normalizeLabels,
} from '@/lib/listMetadata'

describe('label option lists', () => {
  it('are unique and end with the Other bucket', () => {
    for (const list of [FRAMEWORK_OPTIONS, SUBJECT_AREA_OPTIONS]) {
      expect(new Set(list).size).toBe(list.length)
      expect(list[list.length - 1]).toBe('Other')
    }
  })
})

describe('normalizeLabels', () => {
  it('trims, drops blanks and de-duplicates while keeping order', () => {
    expect(
      normalizeLabels([' SOC 2 ', 'HIPAA', '', 'SOC 2', '   ', 'HIPAA'])
    ).toEqual(['SOC 2', 'HIPAA'])
  })

  it('falls back when nothing usable is provided', () => {
    expect(normalizeLabels(null)).toEqual(['Other'])
    expect(normalizeLabels(undefined)).toEqual(['Other'])
    expect(normalizeLabels(['', '  '])).toEqual(['Other'])
    expect(normalizeLabels([], 'Unlabelled')).toEqual(['Unlabelled'])
  })

  it('does not mutate its input', () => {
    const input = [' a ', 'a']
    normalizeLabels(input)
    expect(input).toEqual([' a ', 'a'])
  })
})

describe('formatCreatedAt', () => {
  beforeEach(() => {
    vi.stubEnv('TZ', 'UTC')
  })
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('renders a placeholder for missing or invalid dates', () => {
    expect(formatCreatedAt(null)).toBe('Created —')
    expect(formatCreatedAt(undefined)).toBe('Created —')
    expect(formatCreatedAt('')).toBe('Created —')
    expect(formatCreatedAt('not-a-date')).toBe('Created —')
  })

  it('formats a valid ISO timestamp with month, day and year', () => {
    const out = formatCreatedAt('2026-03-05T14:07:00Z')
    expect(out.startsWith('Created ')).toBe(true)
    expect(out).toContain('2026')
    expect(out).toMatch(/Mar/)
    expect(out).toMatch(/\b5\b/)
  })
})
