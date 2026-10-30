import { describe, expect, it } from 'vitest'
import {
  DEAL_SCHEMA,
  parseDeal,
  parseDealAnalytics,
  parseDealList,
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
