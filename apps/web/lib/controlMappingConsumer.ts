/**
 * Typed reader for question-to-control mapping decisions.
 *
 * Suggest is the read. Confirm, override, and rollback are the writes.
 * Precedence is override, then confirmation, then proposal. A payload that
 * disagrees with that order is rejected. This module has no imports so the
 * API contract test can load it with Node's type stripper.
 */

export const MAPPING_STATES = ['proposed', 'confirmed', 'overridden'] as const

export type MappingState = (typeof MAPPING_STATES)[number]

export const MAPPING_PRECEDENCE = {
  proposed: 1,
  confirmed: 2,
  overridden: 3,
} as const

export type MappingPrecedence = (typeof MAPPING_PRECEDENCE)[MappingState]

type MappingCore = {
  control_ids: number[]
  state: MappingState
  version: number | null
  precedence: MappingPrecedence
  rationale: string | null
  reviewed_by_user_id: number | null
  reviewed_at: string | null
}

export type MappingSuggestion = MappingCore & {
  confidence: number
  has_override: boolean
  reason: string
}

export type MappingDecision = MappingCore & {
  id: number
  question_hash: string
  version: number
  updated: boolean
  precedence_held: boolean
}

export type MappingContract = {
  state: MappingState
  version: number | null
  precedence: MappingPrecedence
  precedence_held: boolean
  control_ids: number[]
}

function fail(message: string): never {
  throw new Error(message)
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    fail('mapping response is missing')
  return value as Record<string, unknown>
}

function mappingState(value: unknown): MappingState {
  if (value !== 'proposed' && value !== 'confirmed' && value !== 'overridden')
    fail('mapping state is unknown')
  return value
}

function controlIds(value: unknown): number[] {
  if (!Array.isArray(value)) fail('mapping control ids are missing')
  return value.map((item) => {
    if (typeof item !== 'number' || !Number.isSafeInteger(item) || item <= 0)
      fail('mapping control id is invalid')
    return item
  })
}

function nullableText(value: unknown, label: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string') fail(`${label} is invalid`)
  return value
}

function reviewedAt(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !Number.isFinite(Date.parse(value)))
    fail('mapping reviewed at is invalid')
  return value
}

function reviewer(value: unknown): number | null {
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0)
    fail('mapping reviewer is invalid')
  return value
}

function precedenceFor(state: MappingState, value: unknown): MappingPrecedence {
  const expected = MAPPING_PRECEDENCE[state]
  if (value !== expected) fail('mapping precedence does not match state')
  return expected
}

function versionValue(value: unknown, required: boolean): number | null {
  if (value === null && !required) return null
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1)
    fail('mapping version is invalid')
  return value
}

function core(
  value: Record<string, unknown>,
  versionRequired: boolean
): MappingCore {
  const state = mappingState(value.state)
  return {
    control_ids: controlIds(value.control_ids),
    state,
    version: versionValue(value.version, versionRequired),
    precedence: precedenceFor(state, value.precedence),
    rationale: nullableText(value.rationale, 'mapping rationale'),
    reviewed_by_user_id: reviewer(value.reviewed_by_user_id),
    reviewed_at: reviewedAt(value.reviewed_at),
  }
}

export function parseMappingSuggestion(value: unknown): MappingSuggestion {
  const body = record(value)
  const shared = core(body, false)
  if (
    typeof body.confidence !== 'number' ||
    !Number.isFinite(body.confidence) ||
    body.confidence < 0 ||
    body.confidence > 1
  )
    fail('mapping confidence is invalid')
  if (typeof body.has_override !== 'boolean')
    fail('mapping override flag is invalid')
  if (body.has_override !== (shared.state === 'overridden'))
    fail('mapping override flag does not match state')
  if (typeof body.reason !== 'string' || !body.reason.trim())
    fail('mapping reason is invalid')
  return {
    ...shared,
    confidence: body.confidence,
    has_override: body.has_override,
    reason: body.reason,
  }
}

export function parseMappingDecision(value: unknown): MappingDecision {
  const body = record(value)
  const shared = core(body, true)
  if (shared.version === null) fail('mapping version is invalid')
  if (
    typeof body.id !== 'number' ||
    !Number.isSafeInteger(body.id) ||
    body.id <= 0
  )
    fail('mapping id is invalid')
  if (typeof body.question_hash !== 'string' || !body.question_hash)
    fail('mapping question hash is invalid')
  if (
    typeof body.updated !== 'boolean' ||
    typeof body.precedence_held !== 'boolean'
  )
    fail('mapping result flags are invalid')
  return {
    ...shared,
    version: shared.version,
    id: body.id,
    question_hash: body.question_hash,
    updated: body.updated,
    precedence_held: body.precedence_held,
  }
}

export function acceptMappingContract(
  kind: 'suggest' | 'decision',
  payload: unknown
): MappingContract {
  if (kind === 'suggest') {
    const parsed = parseMappingSuggestion(payload)
    return {
      state: parsed.state,
      version: parsed.version,
      precedence: parsed.precedence,
      precedence_held: false,
      control_ids: parsed.control_ids,
    }
  }
  if (kind === 'decision') {
    const parsed = parseMappingDecision(payload)
    return {
      state: parsed.state,
      version: parsed.version,
      precedence: parsed.precedence,
      precedence_held: parsed.precedence_held,
      control_ids: parsed.control_ids,
    }
  }
  fail('mapping contract kind is unknown')
}

export function mappingSuggestPath(question: string): string {
  return `/api/compliance/control-mappings/suggest?${new URLSearchParams({
    question,
  }).toString()}`
}

export function parseControlIdText(value: string): number[] | null {
  const trimmed = value.trim()
  if (!trimmed) return []
  const ids: number[] = []
  for (const part of trimmed.split(',')) {
    const token = part.trim()
    if (!/^[1-9]\d*$/.test(token)) return null
    const id = Number(token)
    if (!Number.isSafeInteger(id) || id <= 0) return null
    ids.push(id)
  }
  return ids
}
