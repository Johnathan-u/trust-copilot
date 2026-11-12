import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fetchMappingSuggestion,
  postMappingDecision,
} from '@/lib/controlMappingClient'
import { mappingSuggestPath } from '@/lib/controlMappingConsumer'

const question = 'How do you review access?'
const suggestion = {
  control_ids: [9],
  confidence: 1,
  has_override: true,
  reason: 'Human override takes precedence over confirmation and proposal.',
  state: 'overridden',
  version: 3,
  precedence: 3,
  rationale: 'Use the reviewed control.',
  reviewed_by_user_id: 4,
  reviewed_at: '2026-11-11T10:05:00',
}
const decision = {
  id: 15,
  question_hash: 'abc123',
  control_ids: [9],
  state: 'overridden',
  version: 3,
  rationale: 'Use the reviewed control.',
  precedence: 3,
  reviewed_by_user_id: 4,
  reviewed_at: '2026-11-11T10:05:00.123456',
  updated: false,
  precedence_held: true,
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('control mapping client', () => {
  it('reads a suggestion and rejects a malformed success', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = []
    vi.stubGlobal('fetch', (url: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(url), init })
      return Promise.resolve(json(suggestion))
    })
    await expect(fetchMappingSuggestion(question)).resolves.toEqual(suggestion)
    expect(calls[0]?.url).toBe(mappingSuggestPath(question))
    expect(calls[0]?.init.method).toBeUndefined()
    expect(calls[0]?.init.credentials).toBe('include')
    expect(calls[0]?.init.cache).toBe('no-store')
    vi.stubGlobal('fetch', () => Promise.resolve(json({ state: 'overridden' })))
    await expect(fetchMappingSuggestion(question)).rejects.toThrow(
      'mapping control ids are missing'
    )
  })

  it('posts the decision with its idempotency key and rejects a denial', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = []
    vi.stubGlobal('fetch', (url: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(url), init })
      return Promise.resolve(json(decision))
    })
    await expect(
      postMappingDecision('confirm', { question, control_ids: [9] }, 'key-1')
    ).resolves.toEqual(decision)
    expect(calls[0]?.url).toBe('/api/compliance/control-mappings/confirm')
    expect(calls[0]?.init.method).toBe('POST')
    expect(calls[0]?.init.credentials).toBe('include')
    expect(new Headers(calls[0]?.init.headers).get('Idempotency-Key')).toBe(
      'key-1'
    )
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({
      question,
      control_ids: [9],
    })
    vi.stubGlobal('fetch', () =>
      Promise.resolve(json({ detail: 'Insufficient permissions' }, 403))
    )
    await expect(
      postMappingDecision('rollback', { question }, 'key-2')
    ).rejects.toThrow()
  })
})
