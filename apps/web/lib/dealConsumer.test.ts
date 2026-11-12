import { describe, expect, it } from 'vitest'
import {
  DEAL_SCHEMA,
  parseDeal,
  parseDealAnalytics,
  parseDealList,
  parseDealRisk,
  parseDealRoom,
} from '@/lib/dealConsumer'

function deal(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: DEAL_SCHEMA,
    id: 7,
    workspace_id: 4,
    company_name: 'Synthetic Buyer Co',
    buyer_contact_name: null,
    buyer_contact_email: null,
    deal_value_arr: '990001.23',
    currency: 'XTS',
    stage: 'evaluation',
    close_date: '2026-06-30T00:00:00',
    expected_close_date: '2026-06-30',
    actual_close_date: null,
    requested_frameworks: [],
    linked_questionnaire_ids: [11],
    linked_document_ids: [12],
    room_id: 13,
    crm_source: null,
    crm_external_id: null,
    owner_user_id: 5,
    notes: null,
    created_at: '2026-01-02T03:04:05',
    ...overrides,
  }
}

describe('deal consumer', () => {
  it('preserves a legacy amount with explicitly unknown currency', () => {
    const parsed = parseDeal(
      deal({ deal_value_arr: '100000.00', currency: null })
    )
    expect(parsed.deal_value_arr).toBe('100000.00')
    expect(parsed.currency).toBeNull()
  })

  it('accepts unavailable monetary totals without turning them into zero', () => {
    expect(
      parseDealAnalytics({
        revenue_won: null,
        revenue_pipeline: null,
        win_rate: null,
      })
    ).toEqual({ revenue_won: null, revenue_pipeline: null, win_rate: null })
  })
  it('reads a decimal amount, typed dates, stage, owner, and refs', () => {
    const parsed = parseDeal(deal())
    expect(parsed.deal_value_arr).toBe('990001.23')
    expect(parsed.currency).toBe('XTS')
    expect(parsed.expected_close_date).toBe('2026-06-30')
    expect(parsed.actual_close_date).toBeNull()
    expect(parsed.stage).toBe('evaluation')
    expect(parsed.owner_user_id).toBe(5)
    expect(parsed.linked_document_ids).toEqual([12])
    expect(parsed.room_id).toBe(13)
    expect(parseDealList({ deals: [deal()] })).toHaveLength(1)
  })

  it('rejects a float amount and an unknown stage', () => {
    expect(() => parseDeal(deal({ deal_value_arr: 990001.23 }))).toThrow(
      /decimal string/
    )
    expect(() => parseDeal(deal({ stage: 'won' }))).toThrow(/stage/)
    expect(() => parseDeal(deal({ schema_version: 'deals/v0' }))).toThrow(
      /schema/
    )
  })

  it('reads analytics amounts from stored strings and allows an empty win rate', () => {
    expect(
      parseDealAnalytics({
        revenue_won: '990001.23',
        revenue_pipeline: '0.00',
        win_rate: null,
      })
    ).toEqual({
      revenue_won: '990001.23',
      revenue_pipeline: '0.00',
      win_rate: null,
    })
    expect(() =>
      parseDealAnalytics({
        revenue_won: 990001.23,
        revenue_pipeline: '0.00',
        win_rate: 0,
      })
    ).toThrow(/decimal string/)
  })
})

it.each([
  { id: 0 },
  { id: 1.5 },
  { workspace_id: Number.MAX_SAFE_INTEGER + 1 },
  { owner_user_id: -1 },
  { linked_document_ids: [NaN] },
  { expected_close_date: '2026-02-30' },
  { actual_close_date: '0000-01-01' },
  { deal_value_arr: '10000000000000000.00' },
])('rejects an invalid typed deal acknowledgment: %j', (fields) => {
  expect(() => parseDeal(deal(fields))).toThrow()
})

function risk(overrides: Record<string, unknown> = {}) {
  return {
    deal_id: 7,
    company_name: 'Synthetic Buyer Co',
    deal_value_arr: '990001.23',
    stage: 'evaluation',
    risk_score: 4,
    revenue_at_risk: '10.00',
    breakdown: {
      unanswered_questions: 1,
      low_confidence_answers: 0,
      unapproved_answers: 1,
      stale_evidence: 0,
      total_questions: 2,
    },
    ...overrides,
  }
}

function room(overrides: Record<string, unknown> = {}) {
  return {
    deal_id: 7,
    company_name: 'Synthetic Buyer Co',
    stage: 'evaluation',
    access_token: 'synthetic-room-marker',
    questionnaires: [
      {
        questionnaire_id: 11,
        name: 'Synthetic security questions',
        proven: 1,
        pending: 1,
        total: 2,
        questions: [
          {
            question_id: 5,
            text: 'Synthetic question',
            answer_status: 'proven',
            answer_text: null,
          },
          {
            question_id: 6,
            text: 'Second synthetic question',
            answer_status: 'pending',
            answer_text: 'Synthetic answer',
          },
        ],
      },
    ],
    trust_center_articles: [
      {
        id: 3,
        title: 'Synthetic trust article',
        slug: 'synthetic-trust-article',
      },
    ],
    summary: { total_questionnaires: 1, total_articles: 1 },
    ...overrides,
  }
}

describe('deal risk and room consumers', () => {
  it('keeps a null revenue amount and drops the room token', () => {
    expect(
      parseDealRisk(risk({ revenue_at_risk: null, deal_value_arr: null }))
    ).toMatchObject({
      revenue_at_risk: null,
      deal_value_arr: null,
      risk_score: 4,
    })
    const parsed = parseDealRoom(room())
    expect(parsed.questionnaires[0].questions[1].answer_text).toBe(
      'Synthetic answer'
    )
    expect(parsed).not.toHaveProperty('access_token')
    expect(JSON.stringify(parsed)).not.toContain('synthetic-room-marker')
  })

  it('accepts an empty room without turning it into an error', () => {
    expect(
      parseDealRoom(
        room({
          questionnaires: [],
          trust_center_articles: [],
          summary: { total_questionnaires: 0, total_articles: 0 },
        })
      ).summary
    ).toEqual({ total_questionnaires: 0, total_articles: 0 })
  })

  it.each([
    ['float revenue', risk({ revenue_at_risk: 10 })],
    ['missing breakdown', risk({ breakdown: { unanswered_questions: 1 } })],
    ['negative score', risk({ risk_score: -1 })],
    ['unknown stage', risk({ stage: 'won' })],
    ['unsafe score', risk({ risk_score: Number.MAX_SAFE_INTEGER + 1 })],
  ])('rejects malformed risk (%s)', (_name, body) => {
    expect(() => parseDealRisk(body)).toThrow()
  })

  it.each([
    ['missing token', room({ access_token: '   ' })],
    [
      'summary mismatch',
      room({ summary: { total_questionnaires: 2, total_articles: 1 } }),
    ],
    [
      'duplicate questionnaire',
      room({
        questionnaires: [
          room().questionnaires[0],
          { ...room().questionnaires[0] },
        ],
        summary: { total_questionnaires: 2, total_articles: 1 },
      }),
    ],
    [
      'unknown answer status',
      room({
        questionnaires: [
          {
            ...room().questionnaires[0],
            questions: [
              {
                question_id: 5,
                text: 'Synthetic question',
                answer_status: 'published',
                answer_text: null,
              },
            ],
            proven: 0,
            pending: 1,
            total: 1,
          },
        ],
      }),
    ],
    [
      'count mismatch',
      room({
        questionnaires: [
          { ...room().questionnaires[0], proven: 2, pending: 2, total: 2 },
        ],
      }),
    ],
  ])('rejects a partial room (%s)', (_name, body) => {
    expect(() => parseDealRoom(body)).toThrow()
  })
})

it('preserves the largest supported exact amount and a leap day', () => {
  expect(
    parseDeal(
      deal({
        deal_value_arr: '9999999999999999.99',
        expected_close_date: '2028-02-29',
      })
    ).deal_value_arr
  ).toBe('9999999999999999.99')
})
