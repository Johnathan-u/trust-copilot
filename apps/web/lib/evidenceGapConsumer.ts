export const EVIDENCE_GAP_SCHEMA = 'evidence-gap-ownership/v1'

export type EvidenceGapView = {
  schema_version: typeof EVIDENCE_GAP_SCHEMA
  id: number
  status: string
  gap_type: string
  control_id: number | null
  question_id: number | null
  evidence_ids: number[]
  age_days: number
  owner_user_id: number | null
  owner_missing: boolean
  priority: string
  close_reason: string | null
  duplicate: {
    duplicate: boolean
    canonical_id: number | null
    open_ids: number[]
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseEvidenceGap(body: unknown): EvidenceGapView {
  if (!isRecord(body)) throw new Error('evidence gap response is missing')
  if (body.schema_version !== EVIDENCE_GAP_SCHEMA) {
    throw new Error('evidence gap schema is not recognized')
  }
  if (typeof body.id !== 'number' || typeof body.status !== 'string') {
    throw new Error('evidence gap identity is missing')
  }
  if (typeof body.age_days !== 'number' || typeof body.priority !== 'string') {
    throw new Error('evidence gap ownership is missing')
  }
  if (typeof body.owner_missing !== 'boolean') {
    throw new Error('evidence gap owner is missing')
  }
  if (!isRecord(body.duplicate) || !Array.isArray(body.duplicate.open_ids)) {
    throw new Error('evidence gap duplicate explanation is missing')
  }
  const evidenceIds = Array.isArray(body.evidence_ids)
    ? body.evidence_ids.filter((id): id is number => typeof id === 'number')
    : []
  return {
    schema_version: EVIDENCE_GAP_SCHEMA,
    id: body.id,
    status: body.status,
    gap_type: typeof body.gap_type === 'string' ? body.gap_type : '',
    control_id: typeof body.control_id === 'number' ? body.control_id : null,
    question_id: typeof body.question_id === 'number' ? body.question_id : null,
    evidence_ids: evidenceIds,
    age_days: body.age_days,
    owner_user_id:
      typeof body.owner_user_id === 'number' ? body.owner_user_id : null,
    owner_missing: body.owner_missing,
    priority: body.priority,
    close_reason:
      typeof body.close_reason === 'string' ? body.close_reason : null,
    duplicate: {
      duplicate: body.duplicate.duplicate === true,
      canonical_id:
        typeof body.duplicate.canonical_id === 'number'
          ? body.duplicate.canonical_id
          : null,
      open_ids: body.duplicate.open_ids.filter(
        (id): id is number => typeof id === 'number'
      ),
    },
  }
}
