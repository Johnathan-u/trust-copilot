import { describe, expect, it } from 'vitest'
import {
  acceptMappingContract,
  parseControlIdText,
  parseMappingDecision,
  parseMappingSuggestion,
} from '@/lib/controlMappingConsumer'

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

describe('control mapping reader', () => {
  it('accepts a suggestion and a decision, and agrees on a second read', () => {
    expect(parseMappingSuggestion(suggestion)).toEqual(suggestion)
    expect(parseMappingSuggestion(suggestion)).toEqual(
      parseMappingSuggestion(JSON.parse(JSON.stringify(suggestion)))
    )
    expect(parseMappingDecision(decision)).toEqual(decision)
    expect(
      acceptMappingContract('suggest', { ...suggestion, version: null })
    ).toEqual({
      state: 'overridden',
      version: null,
      precedence: 3,
      precedence_held: false,
      control_ids: [9],
    })
    expect(
      acceptMappingContract('suggest', {
        ...suggestion,
        state: 'proposed',
        has_override: false,
        precedence: 1,
        confidence: 0,
        version: null,
        rationale: null,
        reviewed_by_user_id: null,
        reviewed_at: null,
      }).state
    ).toBe('proposed')
    expect(acceptMappingContract('decision', decision)).toMatchObject({
      state: 'overridden',
      precedence_held: true,
      precedence: 3,
      control_ids: [9],
    })
  })

  it('rejects a malformed payload', () => {
    const broken = [
      null,
      [],
      {},
      { ...suggestion, state: 'approved' },
      { ...suggestion, precedence: 1 },
      { ...suggestion, has_override: false },
      { ...suggestion, control_ids: ['9'] },
      { ...suggestion, control_ids: [0] },
      { ...suggestion, control_ids: [1.5] },
      { ...suggestion, version: '3' },
      { ...suggestion, confidence: 1.5 },
      { ...suggestion, reason: '   ' },
      { ...suggestion, reviewed_at: 'yesterday' },
      { ...suggestion, reviewed_by_user_id: 0 },
      { ...decision, id: '15' },
      { ...decision, question_hash: '' },
      { ...decision, updated: 'false' },
      { ...decision, precedence_held: 1 },
      { ...decision, version: null },
    ]
    for (const payload of broken) {
      expect(() => parseMappingSuggestion(payload)).toThrow()
      expect(() => parseMappingDecision(payload)).toThrow()
    }
    expect(() =>
      acceptMappingContract('suggest', {
        state: 'overridden',
        precedence: 1,
        has_override: true,
      })
    ).toThrow()
  })

  it('reads override control ids and keeps an empty list', () => {
    expect(parseControlIdText('')).toEqual([])
    expect(parseControlIdText(' 9, 10 ')).toEqual([9, 10])
    expect(parseControlIdText('0')).toBeNull()
    expect(parseControlIdText('nope')).toBeNull()
    expect(parseControlIdText('1.5')).toBeNull()
  })
})
