import { describe, expect, it } from 'vitest'

import {
  CARD_STALE_MESSAGE,
  cardCreateFingerprint,
  cardSaveRequest,
  cardSaveResult,
  nextCardCreateKey,
} from '@/lib/dashboard-card-form'

const fields = {
  title: ' Evidence ',
  description: '  ',
  icon: 'document',
  targetRoute: '/dashboard/documents',
  visibility: 'all',
  size: 'medium',
  enabled: true,
}

describe('dashboard card form', () => {
  it('sends the revision the editor loaded and does not send a create key', () => {
    const request = cardSaveRequest({
      card: {
        id: 17,
        updated_at: '2026-11-21T02:03:00.123456',
        is_builtin: false,
      },
      fields,
    })
    expect(request.method).toBe('PATCH')
    expect(request.url).toBe('/api/dashboard/cards/17')
    expect(request.headers['Idempotency-Key']).toBeUndefined()
    expect(request.body).toEqual({
      title: 'Evidence',
      description: null,
      icon: 'document',
      target_route: '/dashboard/documents',
      visibility_scope: 'all',
      size: 'medium',
      is_enabled: true,
      updated_at: '2026-11-21T02:03:00.123456',
    })
  })

  it('does not attach a revision to a built-in card', () => {
    const request = cardSaveRequest({
      card: { is_builtin: true, title: 'Documents' } as {
        is_builtin: boolean
      },
      fields,
      createKey: 'create-1',
    })
    expect(request.method).toBe('POST')
    expect(request.body.updated_at).toBeUndefined()
    expect(request.headers['Idempotency-Key']).toBe('create-1')
  })

  it('keeps one Idempotency-Key when the create body is retried', () => {
    const fingerprint = cardCreateFingerprint(fields)
    const first = nextCardCreateKey(null, fingerprint, () => 'key-a')
    const retry = nextCardCreateKey(first, fingerprint, () => 'key-b')
    expect(retry).toBe(first)
    const changed = nextCardCreateKey(
      retry,
      cardCreateFingerprint({ ...fields, title: 'Other' }),
      () => 'key-c'
    )
    expect(changed.key).toBe('key-c')
    const request = cardSaveRequest({
      card: null,
      fields,
      createKey: retry.key,
    })
    expect(request.method).toBe('POST')
    expect(request.headers['Idempotency-Key']).toBe('key-a')
    expect(request.body.updated_at).toBeUndefined()
  })

  it('treats 409 as a conflict and does not report the card as saved', () => {
    const conflict = cardSaveResult(409, {
      detail: CARD_STALE_MESSAGE,
    })
    expect(conflict).toEqual({
      saved: false,
      conflict: true,
      message: CARD_STALE_MESSAGE,
    })
    const blank = cardSaveResult(409, { detail: '  ' })
    expect(blank).toEqual({
      saved: false,
      conflict: true,
      message: CARD_STALE_MESSAGE,
    })
    expect(cardSaveResult(200, { id: 17 }).saved).toBe(true)
    const rejected = cardSaveResult(422, { detail: 'Invalid target_route' })
    expect(rejected.saved).toBe(false)
    if (rejected.saved === false) expect(rejected.conflict).toBe(false)
  })
})
