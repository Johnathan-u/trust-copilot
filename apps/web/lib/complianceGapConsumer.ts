/**
 * Typed reader for GET /api/compliance/gaps.
 *
 * A gap is gap, unknown, stale, or failed. A clear control is omitted.
 * State, rule, and next step have to agree. This module has no imports so
 * the API contract test can load it with Node's type stripper.
 */

export const GAP_STATES = ['gap', 'unknown', 'stale', 'failed'] as const

export type GapState = (typeof GAP_STATES)[number]

export const GAP_RULES = [
  'no_evidence',
  'not_approved',
  'deleted_document',
  'expired',
  'missing_evidence_row',
  'missing_document',
  'missing_framework',
  'check_error',
] as const

export type GapRule = (typeof GAP_RULES)[number]

export const RULE_STATES: Record<GapRule, GapState> = {
  no_evidence: 'gap',
  not_approved: 'gap',
  deleted_document: 'gap',
  expired: 'stale',
  missing_evidence_row: 'unknown',
  missing_document: 'unknown',
  missing_framework: 'unknown',
  check_error: 'failed',
}

export const RULE_ACTIONS = {
  no_evidence: 'collect_evidence',
  not_approved: 'approve_evidence',
  deleted_document: 'replace_deleted_evidence',
  expired: 'refresh_evidence',
  missing_evidence_row: 'resolve_reference',
  missing_document: 'resolve_reference',
  missing_framework: 'resolve_reference',
  check_error: 'retry_check',
} as const

export type GapAction = (typeof RULE_ACTIONS)[GapRule]

export type GapReason = {
  rule: GapRule
  control_id: number
  evidence_ids: number[]
}

export type GapNextStep = {
  owner_user_id: number | null
  owner_missing: boolean
  action: GapAction
}

export type ComplianceGap = {
  control_id: number
  control_key: string | null
  name: string | null
  framework: string | null
  evidence_count: number
  max_confidence: number | null
  gap_reason: GapRule
  state: GapState
  rule: GapRule
  evidence_ids: number[]
  reason: GapReason
  next_step: GapNextStep
}

export type QuestionnaireRef = {
  questionnaire_id: number | null
  questionnaire_title: string
  question_id: number | null
  question_text_preview: string
}

export type QuestionnaireEvidenceGap = {
  gap_kind: 'questionnaire_mapping_no_evidence'
  control_id: number
  control_key: string | null
  name: string | null
  framework: string | null
  evidence_link_count: number
  questionnaire_refs: QuestionnaireRef[]
}

export type ComplianceGapsResponse = {
  gaps: ComplianceGap[]
  questionnaire_evidence_gaps: QuestionnaireEvidenceGap[]
}

function fail(message: string): never {
  throw new Error(message)
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    fail(`${label} is missing`)
  return value as Record<string, unknown>
}

function required(body: Record<string, unknown>, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(body, key))
    fail(`${key} is missing`)
  return body[key]
}

function positiveId(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value <= 0)
    fail(`${label} is invalid`)
  return value
}

function nullableId(value: unknown, label: string): number | null {
  if (value === null) return null
  return positiveId(value, label)
}

function nullableText(value: unknown, label: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string') fail(`${label} is invalid`)
  return value
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string') fail(`${label} is invalid`)
  return value
}

function idList(value: unknown, label: string): number[] {
  if (!Array.isArray(value)) fail(`${label} is missing`)
  return value.map((item) => positiveId(item, label))
}

function sameIds(left: number[], right: number[]): boolean {
  if (left.length !== right.length) return false
  return left.every((item, index) => item === right[index])
}

function count(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0)
    fail(`${label} is invalid`)
  return value
}

function confidence(value: unknown): number | null {
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value))
    fail('max confidence is invalid')
  return value
}

function gapRule(value: unknown): GapRule {
  if (typeof value !== 'string' || !GAP_RULES.includes(value as GapRule))
    fail('gap rule is unknown')
  return value as GapRule
}

function parseGap(value: unknown): ComplianceGap {
  const body = record(value, 'compliance gap')
  const rule = gapRule(required(body, 'rule'))
  const state = RULE_STATES[rule]
  if (required(body, 'state') !== state) fail('gap state does not match rule')
  if (required(body, 'gap_reason') !== rule)
    fail('gap reason does not match rule')
  const controlId = positiveId(required(body, 'control_id'), 'control id')
  const evidenceIds = idList(required(body, 'evidence_ids'), 'evidence id')
  const reason = record(required(body, 'reason'), 'gap reason')
  const reasonRule = gapRule(required(reason, 'rule'))
  if (reasonRule !== rule) fail('gap reason rule does not match')
  const reasonControl = positiveId(
    required(reason, 'control_id'),
    'reason control id'
  )
  if (reasonControl !== controlId) fail('gap reason control does not match')
  const reasonIds = idList(
    required(reason, 'evidence_ids'),
    'reason evidence id'
  )
  if (!sameIds(reasonIds, evidenceIds))
    fail('gap reason evidence does not match')
  const next = record(required(body, 'next_step'), 'next step')
  const owner = nullableId(required(next, 'owner_user_id'), 'owner')
  const ownerMissing = required(next, 'owner_missing')
  if (typeof ownerMissing !== 'boolean' || ownerMissing !== (owner === null))
    fail('owner missing does not match owner')
  const action = RULE_ACTIONS[rule]
  if (required(next, 'action') !== action) fail('next step does not match rule')
  return {
    control_id: controlId,
    control_key: nullableText(required(body, 'control_key'), 'control key'),
    name: nullableText(required(body, 'name'), 'control name'),
    framework: nullableText(required(body, 'framework'), 'framework'),
    evidence_count: count(required(body, 'evidence_count'), 'evidence count'),
    max_confidence: confidence(required(body, 'max_confidence')),
    gap_reason: rule,
    state,
    rule,
    evidence_ids: evidenceIds,
    reason: {
      rule,
      control_id: controlId,
      evidence_ids: evidenceIds,
    },
    next_step: {
      owner_user_id: owner,
      owner_missing: ownerMissing,
      action,
    },
  }
}

function parseRef(value: unknown): QuestionnaireRef {
  const body = record(value, 'questionnaire ref')
  return {
    questionnaire_id: nullableId(
      required(body, 'questionnaire_id'),
      'questionnaire id'
    ),
    questionnaire_title: text(
      required(body, 'questionnaire_title'),
      'questionnaire title'
    ),
    question_id: nullableId(required(body, 'question_id'), 'question id'),
    question_text_preview: text(
      required(body, 'question_text_preview'),
      'question text'
    ),
  }
}

function parseQuestionnaireGap(value: unknown): QuestionnaireEvidenceGap {
  const body = record(value, 'questionnaire gap')
  if (required(body, 'gap_kind') !== 'questionnaire_mapping_no_evidence')
    fail('questionnaire gap kind is unknown')
  const refs = required(body, 'questionnaire_refs')
  if (!Array.isArray(refs)) fail('questionnaire refs are missing')
  return {
    gap_kind: 'questionnaire_mapping_no_evidence',
    control_id: positiveId(required(body, 'control_id'), 'control id'),
    control_key: nullableText(required(body, 'control_key'), 'control key'),
    name: nullableText(required(body, 'name'), 'control name'),
    framework: nullableText(required(body, 'framework'), 'framework'),
    evidence_link_count: count(
      required(body, 'evidence_link_count'),
      'evidence link count'
    ),
    questionnaire_refs: refs.map((item) => parseRef(item)),
  }
}

export function parseComplianceGaps(value: unknown): ComplianceGapsResponse {
  const body = record(value, 'compliance gaps response')
  const gaps = required(body, 'gaps')
  const questionnaire = required(body, 'questionnaire_evidence_gaps')
  if (!Array.isArray(gaps) || !Array.isArray(questionnaire))
    fail('compliance gap lists are missing')
  return {
    gaps: gaps.map((item) => parseGap(item)),
    questionnaire_evidence_gaps: questionnaire.map((item) =>
      parseQuestionnaireGap(item)
    ),
  }
}
