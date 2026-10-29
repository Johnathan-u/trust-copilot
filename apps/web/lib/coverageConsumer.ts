export const CONTROL_COVERAGE_SCHEMA = 'compliance-coverage-controls/v1'

const PRESERVED_FIELDS = [
  'kpi',
  'framework_coverage',
  'blind_spots',
  'weak_areas',
  'evidence_strength',
  'recommended_evidence',
  'trends',
  'drill_down',
] as const

export type ControlExplanation = {
  control_id: number
  state: string
  rule: string
  effect: 'excluded_from_denominator' | 'excluded_from_numerator' | 'counted'
  denominator_changed: boolean
  framework_id: number | null
}

export type ControlCoverage = {
  schema_version: typeof CONTROL_COVERAGE_SCHEMA
  numerator: number
  denominator: number
  coverage_pct: number
  qualified_control_ids: number[]
  explanations: ControlExplanation[]
}

export type RecommendedEvidence = {
  title: string
  improves_questions: number
  evidence_ids: number[]
  control_ids: number[]
  question_ids: number[]
}

export type CoverageResponse = {
  kpi: Record<string, unknown>
  framework_coverage: unknown[]
  blind_spots: unknown[]
  weak_areas: unknown[]
  evidence_strength: unknown[]
  recommended_evidence: RecommendedEvidence[]
  trends: unknown[]
  drill_down: unknown[]
  control_coverage: ControlCoverage
}

function idList(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is number => typeof item === 'number' && Number.isFinite(item)
  )
}

function recommendation(value: unknown): RecommendedEvidence | null {
  if (!isRecord(value)) return null
  if (
    typeof value.title !== 'string' ||
    typeof value.improves_questions !== 'number' ||
    !Number.isFinite(value.improves_questions)
  ) {
    return null
  }
  return {
    title: value.title,
    improves_questions: value.improves_questions,
    evidence_ids: idList(value.evidence_ids),
    control_ids: idList(value.control_ids),
    question_ids: idList(value.question_ids),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function explanation(value: unknown): ControlExplanation {
  if (!isRecord(value)) throw new Error('coverage explanation is missing')
  const effect = value.effect
  if (
    effect !== 'excluded_from_denominator' &&
    effect !== 'excluded_from_numerator' &&
    effect !== 'counted'
  ) {
    throw new Error('coverage explanation effect is unknown')
  }
  if (typeof value.control_id !== 'number' || typeof value.state !== 'string') {
    throw new Error('coverage explanation is incomplete')
  }
  if (
    typeof value.rule !== 'string' ||
    typeof value.denominator_changed !== 'boolean'
  ) {
    throw new Error('coverage explanation is incomplete')
  }
  let frameworkId: number | null
  if (value.framework_id === null) {
    frameworkId = null
  } else if (typeof value.framework_id === 'number') {
    frameworkId = value.framework_id
  } else {
    throw new Error('coverage explanation framework id is invalid')
  }
  return {
    control_id: value.control_id,
    state: value.state,
    rule: value.rule,
    effect,
    denominator_changed: value.denominator_changed,
    framework_id: frameworkId,
  }
}

export function parseCoverageResponse(body: unknown): CoverageResponse {
  if (!isRecord(body)) throw new Error('coverage response is missing')
  for (const field of PRESERVED_FIELDS) {
    if (!(field in body))
      throw new Error(`coverage response is missing ${field}`)
  }
  const raw = body.control_coverage
  if (!isRecord(raw)) throw new Error('control coverage is missing')
  if (raw.schema_version !== CONTROL_COVERAGE_SCHEMA) {
    throw new Error('control coverage schema is not recognized')
  }
  if (
    typeof raw.numerator !== 'number' ||
    typeof raw.denominator !== 'number'
  ) {
    throw new Error('control coverage counts are missing')
  }
  if (
    !Array.isArray(raw.qualified_control_ids) ||
    !Array.isArray(raw.explanations)
  ) {
    throw new Error('control coverage lists are missing')
  }
  return {
    kpi: body.kpi as Record<string, unknown>,
    framework_coverage: body.framework_coverage as unknown[],
    blind_spots: body.blind_spots as unknown[],
    weak_areas: body.weak_areas as unknown[],
    evidence_strength: body.evidence_strength as unknown[],
    recommended_evidence: Array.isArray(body.recommended_evidence)
      ? body.recommended_evidence
          .map(recommendation)
          .filter((item): item is RecommendedEvidence => item !== null)
      : [],
    trends: body.trends as unknown[],
    drill_down: body.drill_down as unknown[],
    control_coverage: {
      schema_version: CONTROL_COVERAGE_SCHEMA,
      numerator: raw.numerator,
      denominator: raw.denominator,
      coverage_pct: typeof raw.coverage_pct === 'number' ? raw.coverage_pct : 0,
      qualified_control_ids: raw.qualified_control_ids.filter(
        (id): id is number => typeof id === 'number'
      ),
      explanations: raw.explanations.map(explanation),
    },
  }
}

export function denominatorNotes(
  coverage: ControlCoverage
): ControlExplanation[] {
  return coverage.explanations.filter(
    (item) =>
      item.denominator_changed ||
      item.state === 'disabled' ||
      item.state === 'unknown' ||
      item.state === 'stale'
  )
}
