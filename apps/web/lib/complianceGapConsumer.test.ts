import { describe, expect, it } from 'vitest'
import {
  parseComplianceGaps,
  type ComplianceGap,
} from '@/lib/complianceGapConsumer'

function gap(overrides: Record<string, unknown> = {}): ComplianceGap {
  return {
    control_id: 9,
    control_key: null,
    name: 'Synthetic',
    framework: null,
    evidence_count: 0,
    max_confidence: null,
    gap_reason: 'no_evidence',
    state: 'gap',
    rule: 'no_evidence',
    evidence_ids: [],
    reason: { rule: 'no_evidence', control_id: 9, evidence_ids: [] },
    next_step: {
      owner_user_id: null,
      owner_missing: true,
      action: 'collect_evidence',
    },
    ...overrides,
  } as ComplianceGap
}

function response(overrides: Record<string, unknown> = {}) {
  return {
    gaps: [gap()],
    questionnaire_evidence_gaps: [
      {
        gap_kind: 'questionnaire_mapping_no_evidence',
        control_id: 9,
        control_key: 'SYN-1',
        name: 'Synthetic',
        framework: null,
        evidence_link_count: 0,
        questionnaire_refs: [
          {
            questionnaire_id: 4,
            questionnaire_title: 'Synthetic.csv',
            question_id: null,
            question_text_preview: 'Where is the file?',
          },
        ],
      },
    ],
    ...overrides,
  }
}

describe('compliance gap reader', () => {
  it('accepts a gap list and agrees on a second read', () => {
    const payload = response()
    const parsed = parseComplianceGaps(payload)
    expect(parsed).toEqual(payload)
    expect(parseComplianceGaps(JSON.parse(JSON.stringify(payload)))).toEqual(
      parsed
    )
    expect(
      parseComplianceGaps({ gaps: [], questionnaire_evidence_gaps: [] })
    ).toEqual({ gaps: [], questionnaire_evidence_gaps: [] })
    const deleted = gap({
      rule: 'deleted_document',
      gap_reason: 'deleted_document',
      state: 'gap',
      evidence_count: 1,
      evidence_ids: [8],
      max_confidence: 0.5,
      reason: {
        rule: 'deleted_document',
        control_id: 9,
        evidence_ids: [8],
      },
      next_step: {
        owner_user_id: 3,
        owner_missing: false,
        action: 'replace_deleted_evidence',
      },
    })
    expect(
      parseComplianceGaps({ gaps: [deleted], questionnaire_evidence_gaps: [] })
        .gaps[0].rule
    ).toBe('deleted_document')
  })

  it('rejects a malformed payload', () => {
    const broken = [
      null,
      [],
      {},
      { gaps: [], questionnaire_evidence_gaps: null },
      { gaps: 'none', questionnaire_evidence_gaps: [] },
      response({ gaps: [gap({ state: 'clear' })] }),
      response({ gaps: [gap({ rule: 'expired', state: 'gap' })] }),
      response({ gaps: [gap({ gap_reason: 'expired' })] }),
      response({ gaps: [gap({ control_id: '9' })] }),
      response({ gaps: [gap({ control_id: 0 })] }),
      response({ gaps: [gap({ evidence_ids: ['8'] })] }),
      response({ gaps: [gap({ evidence_ids: [1.5] })] }),
      response({
        gaps: [
          gap({
            next_step: {
              owner_user_id: 3,
              owner_missing: true,
              action: 'collect_evidence',
            },
          }),
        ],
      }),
      response({
        gaps: [
          gap({
            reason: { rule: 'no_evidence', control_id: 4, evidence_ids: [] },
          }),
        ],
      }),
      response({
        gaps: [
          gap({
            next_step: {
              owner_user_id: null,
              owner_missing: true,
              action: 'approve_evidence',
            },
          }),
        ],
      }),
      response({
        questionnaire_evidence_gaps: [
          {
            gap_kind: 'other',
            control_id: 9,
            control_key: null,
            name: null,
            framework: null,
            evidence_link_count: 0,
            questionnaire_refs: [],
          },
        ],
      }),
    ]
    for (const payload of broken) {
      expect(() => parseComplianceGaps(payload)).toThrow()
    }
  })
})
