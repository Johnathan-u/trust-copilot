import { describe, expect, it } from 'vitest'

import { parseSalesContact, salesContactHref } from '@/lib/sales-contact'

describe('parseSalesContact', () => {
  it('is hidden when unset', () => {
    expect(parseSalesContact(undefined)).toBeNull()
    expect(parseSalesContact(null)).toBeNull()
    expect(parseSalesContact('')).toBeNull()
    expect(parseSalesContact('   ')).toBeNull()
  })

  it('turns an email into a mailto link', () => {
    expect(parseSalesContact('owner.contact@example.com')).toBe(
      'mailto:owner.contact@example.com?subject=Workspace%20access'
    )
    expect(parseSalesContact('  owner.contact@example.com  ')).toBe(
      'mailto:owner.contact@example.com?subject=Workspace%20access'
    )
  })

  it('accepts an https URL', () => {
    expect(parseSalesContact('https://example.com/contact')).toBe(
      'https://example.com/contact'
    )
    expect(parseSalesContact('https://example.com')).toBe(
      'https://example.com/'
    )
  })

  it('ignores anything else', () => {
    expect(parseSalesContact('http://example.com/contact')).toBeNull()
    expect(parseSalesContact('javascript:alert(1)')).toBeNull()
    expect(parseSalesContact('mailto:owner.contact@example.com')).toBeNull()
    expect(parseSalesContact('not an email')).toBeNull()
    expect(parseSalesContact('owner.contact@')).toBeNull()
    expect(parseSalesContact('ftp://example.com/contact')).toBeNull()
  })
})

describe('salesContactHref', () => {
  it('reads the value it is given and hides an invalid one', () => {
    expect(salesContactHref('https://example.com/contact')).toBe(
      'https://example.com/contact'
    )
    expect(salesContactHref('nope')).toBeNull()
  })
})
