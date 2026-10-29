import { describe, expect, it } from 'vitest'
import {
  EVIDENCE_GAP_SCHEMA,
  parseEvidenceGap,
} from '@/lib/evidenceGapConsumer'

function body(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: EVIDENCE_GAP_SCHEMA,
    id: 4,
    status: 'open',
    gap_type: 'control_check',
    control_id: 9,
    question_id: null,
    evidence_ids: [],
    age_days: 20,
    owner_user_id: 3,
    owner_missing: false,
    priority: 'high',
    close_reason: null,
    duplicate: { duplicate: false, canonical_id: 4, open_ids: [4] },
    ...overrides,
  }
}

describe('parseEvidenceGap', () => {
  it('keeps ownership, priority, and the version', () => {
    const parsed = parseEvidenceGap(body())
    expect(parsed.schema_version).toBe(EVIDENCE_GAP_SCHEMA)
    expect(parsed.age_days).toBe(20)
    expect(parsed.priority).toBe('high')
    expect(parsed.owner_user_id).toBe(3)
    expect(parsed.owner_missing).toBe(false)
  })

  it('agrees across a second parse', () => {
    const payload = body()
    expect(parseEvidenceGap(payload)).toEqual(parseEvidenceGap(payload))
  })

  it('rejects an unversioned payload', () => {
    expect(() => parseEvidenceGap(body({ schema_version: 'other' }))).toThrow(
      /schema is not recognized/
    )
  })
})
