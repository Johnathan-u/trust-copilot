export const DEAL_SCHEMA = 'deals/v1'

export const DEAL_STAGES = [
  'prospect',
  'discovery',
  'evaluation',
  'negotiation',
  'closed_won',
  'closed_lost',
] as const

export type DealStage = (typeof DEAL_STAGES)[number]

export type DealRecord = {
  schema_version: typeof DEAL_SCHEMA
  id: number
  workspace_id: number
  company_name: string
  buyer_contact_name: string | null
  buyer_contact_email: string | null
  deal_value_arr: string | null
  currency: string | null
  stage: DealStage
  close_date: string | null
  expected_close_date: string | null
  actual_close_date: string | null
  requested_frameworks: string[]
  linked_questionnaire_ids: number[]
  linked_document_ids: number[]
  room_id: number | null
  crm_source: string | null
  crm_external_id: string | null
  owner_user_id: number | null
  notes: string | null
  created_at: string | null
}

const AMOUNT = /^(0|[1-9]\d*)\.\d{2}$/
const CURRENCY = /^[A-Z]{3}$/
const DAY = /^\d{4}-\d{2}-\d{2}$/

function validId(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0
}

function validDay(value: string): boolean {
  if (!DAY.test(value) || value.startsWith('0000')) return false
  const date = new Date(`${value}T00:00:00Z`)
  return (
    !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string')
    throw new Error(`${label} must be a string or null`)
  return value
}

function nullableId(value: unknown, label: string): number | null {
  if (value === null) return null
  if (validId(value)) return value
  throw new Error(`${label} is invalid`)
}

function idList(value: unknown, label: string): number[] {
  if (!Array.isArray(value) || value.some((item) => !validId(item))) {
    throw new Error(`${label} must be a list of ids`)
  }
  return value
}

function amount(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !AMOUNT.test(value)) {
    throw new Error('deal amount must be a decimal string')
  }
  return value
}

export function parseDeal(value: unknown): DealRecord {
  if (!isRecord(value)) throw new Error('deal response is missing')
  if (value.schema_version !== DEAL_SCHEMA)
    throw new Error('deal schema is unknown')
  if (!validId(value.id) || !validId(value.workspace_id)) {
    throw new Error('deal id is invalid')
  }
  if (typeof value.company_name !== 'string')
    throw new Error('deal company is invalid')
  const stage = value.stage
  if (typeof stage !== 'string' || !DEAL_STAGES.includes(stage as DealStage)) {
    throw new Error('deal stage is unknown')
  }
  const dealAmount = amount(value.deal_value_arr)
  if (dealAmount !== null && !/^(0|[1-9]\d{0,15})\.\d{2}$/.test(dealAmount))
    throw new Error('deal amount exceeds the supported decimal range')
  const currency = nullableString(value.currency, 'currency')
  if (currency !== null && !CURRENCY.test(currency))
    throw new Error('currency is invalid')
  const expected = nullableString(
    value.expected_close_date,
    'expected close date'
  )
  const actual = nullableString(value.actual_close_date, 'actual close date')
  if (expected !== null && !validDay(expected))
    throw new Error('expected close date is invalid')
  if (actual !== null && !validDay(actual))
    throw new Error('actual close date is invalid')
  const owner = nullableId(value.owner_user_id, 'owner')
  const room = nullableId(value.room_id, 'room')
  if (!Array.isArray(value.requested_frameworks)) {
    throw new Error('requested frameworks must be a list')
  }
  return {
    schema_version: DEAL_SCHEMA,
    id: value.id,
    workspace_id: value.workspace_id,
    company_name: value.company_name,
    buyer_contact_name: nullableString(value.buyer_contact_name, 'buyer name'),
    buyer_contact_email: nullableString(
      value.buyer_contact_email,
      'buyer email'
    ),
    deal_value_arr: dealAmount,
    currency,
    stage: stage as DealStage,
    close_date: nullableString(value.close_date, 'close date'),
    expected_close_date: expected,
    actual_close_date: actual,
    requested_frameworks: value.requested_frameworks.map((item) => {
      if (typeof item !== 'string')
        throw new Error('requested frameworks must be strings')
      return item
    }),
    linked_questionnaire_ids: idList(
      value.linked_questionnaire_ids,
      'questionnaires'
    ),
    linked_document_ids: idList(value.linked_document_ids, 'documents'),
    room_id: room,
    crm_source: nullableString(value.crm_source, 'crm source'),
    crm_external_id: nullableString(value.crm_external_id, 'crm id'),
    owner_user_id: owner,
    notes: nullableString(value.notes, 'notes'),
    created_at: nullableString(value.created_at, 'created at'),
  }
}

export function parseDealList(value: unknown): DealRecord[] {
  if (!isRecord(value) || !Array.isArray(value.deals)) {
    throw new Error('deal list is missing')
  }
  return value.deals.map((deal) => parseDeal(deal))
}

export function parseDealAnalytics(value: unknown): {
  revenue_won: string | null
  revenue_pipeline: string | null
  win_rate: string | null
} {
  if (!isRecord(value)) throw new Error('deal analytics is missing')
  const revenueWon = amount(value.revenue_won)
  const revenuePipeline = amount(value.revenue_pipeline)
  const winRateValue = value.win_rate
  let winRate: string | null
  if (winRateValue === null) {
    winRate = null
  } else if (
    typeof winRateValue === 'string' &&
    /^(0|[1-9]\d*)\.\d$/.test(winRateValue)
  ) {
    winRate = winRateValue
  } else {
    throw new Error('win rate must be a one-decimal string or null')
  }
  return {
    revenue_won: revenueWon,
    revenue_pipeline: revenuePipeline,
    win_rate: winRate,
  }
}
