import { describe, expect, it } from 'vitest'

import {
  DEFAULT_POST_LOGIN_PATH,
  safePostLoginPath,
} from '@/lib/post-login-path'

const fallback = DEFAULT_POST_LOGIN_PATH

describe('safePostLoginPath', () => {
  it('keeps same-origin relative paths, including query strings and hashes', () => {
    const safe = [
      '/dashboard',
      '/dashboard/review/12',
      '/dashboard?tab=open',
      '/dashboard/review/12?tab=open#section',
      '/questionnaires/9?x=1&y=2#answer',
      '/login?next=/dashboard',
      '/',
    ]
    for (const path of safe) {
      expect(safePostLoginPath(path)).toBe(path)
    }
  })

  it('falls back when next is missing', () => {
    expect(safePostLoginPath(null)).toBe(fallback)
    expect(safePostLoginPath(undefined)).toBe(fallback)
    expect(safePostLoginPath('')).toBe(fallback)
  })

  it('rejects absolute URLs, protocol-relative URLs, and other non-paths', () => {
    const rejected = [
      'https://example.com',
      'http://example.com',
      'https://example.com/dashboard',
      'HTTP://example.com/phish',
      'https://post-login.invalid/dashboard',
      '//example.com',
      '//example.com/path',
      '///example.com',
      '//post-login.invalid/dashboard',
      'dashboard',
      'dashboard/review/12',
      ' /dashboard',
      '\t//example.com',
      'mailto:person@example.com',
      'blob:https://example.com/uuid',
    ]
    for (const value of rejected) {
      expect(safePostLoginPath(value)).toBe(fallback)
    }
  })

  it('rejects backslash tricks', () => {
    const rejected = [
      '/\\example.com',
      '/\\\\example.com',
      '/\\/example.com',
      '\\\\example.com',
      '/\\example.com?x=1',
      '/dashboard\\..\\..\\example.com',
      '/\t/example.com',
    ]
    for (const value of rejected) {
      expect(safePostLoginPath(value)).toBe(fallback)
    }
  })

  it('rejects javascript: and data: schemes', () => {
    const rejected = [
      'javascript:alert(1)',
      'JAVASCRIPT:alert(1)',
      'javascript:alert(1)//',
      'java\nscript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'data:text/html,hi',
      ' DaTa:text/html,hi',
    ]
    for (const value of rejected) {
      expect(safePostLoginPath(value)).toBe(fallback)
    }
  })

  it('rejects encoded absolute, protocol-relative, scheme, and backslash variants', () => {
    const rejected = [
      '%2F%2Fexample.com',
      '%2f%2fexample.com',
      '/%2F%2Fexample.com',
      '/%2f/example.com',
      'https%3A%2F%2Fexample.com',
      'HTTPS%3A%2F%2Fexample.com',
      'javascript%3Aalert(1)',
      'JaVaScRiPt%3Aalert(1)',
      'data%3Atext/html,hi',
      '/%5Cexample.com',
      '/%5c%5cexample.com',
      '/%252f%252fexample.com',
      '/%255c%255cexample.com',
      '/%25252f%25252fexample.com',
      '/%09//example.com',
      '/%09%2f%2fexample.com',
      '/%5C%2F%2Fexample.com',
    ]
    for (const value of rejected) {
      expect(safePostLoginPath(value)).toBe(fallback)
    }
  })

  it('keeps an encoded slash that stays inside a query string', () => {
    const path = '/dashboard?next=%2Fdashboard%2Fsettings#done'
    expect(safePostLoginPath(path)).toBe(path)
  })
})
