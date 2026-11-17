import { expect, it } from 'vitest'
import { buyerAccessLink, spaceLiveness } from '@/lib/shareable-space-link'

const now = Date.parse('2026-06-01T00:00:00Z')

it('treats an active unexpired space as live', () => {
  expect(
    spaceLiveness({ is_active: true, expires_at: '2099-01-01T00:00:00Z' }, now)
  ).toBe('live')
  expect(spaceLiveness({ is_active: true, expires_at: null }, now)).toBe('live')
  expect(
    spaceLiveness({ is_active: false, expires_at: '2099-01-01T00:00:00Z' }, now)
  ).toBe('inactive')
  expect(
    spaceLiveness({ is_active: true, expires_at: '2000-01-01T00:00:00Z' }, now)
  ).toBe('expired')
})

it('builds the buyer link without storing the token', () => {
  expect(buyerAccessLink('https://app.example', 'a+b/c')).toBe(
    'https://app.example/api/shareable-spaces/access?token=a%2Bb%2Fc'
  )
  expect(buyerAccessLink('https://app.example/', 'plain')).toBe(
    'https://app.example/api/shareable-spaces/access?token=plain'
  )
})
