import { recordFromPayload } from '@/lib/section-load'

export type Gap = {
  workspace_id: number
  id: number
  questionnaire_id: number | null
  control_id: number | null
  reason: string | null
  suggested_evidence_doc_title: string | null
  status: 'open' | 'accepted' | 'dismissed' | 'resolved'
  priority: 'high' | 'medium' | 'low' | 'settled'
  age_days: number
  owner_user_id: number | null
  owner_missing: boolean
}
export const statusLabels = {
  open: 'Open',
  accepted: 'Accepted',
  dismissed: 'Dismissed',
  resolved: 'Resolved',
}
export const priorityLabels = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  settled: 'Settled',
}
export function positiveId(value: unknown) {
  return Number.isSafeInteger(value) && Number(value) > 0
}
function nullableId(value: unknown) {
  return value === null || positiveId(value)
}
export function parseGaps(input: unknown): Gap[] {
  const root = recordFromPayload(input)
  if (
    root.schema_version !== 'evidence-gap-ownership/v1' ||
    !Array.isArray(root.gaps)
  )
    throw new Error('Unsupported gap response')
  const ids = new Set<number>()
  return root.gaps.map((value) => {
    const row = recordFromPayload(value)
    if (
      row.schema_version !== root.schema_version ||
      !positiveId(row.id) ||
      !positiveId(row.workspace_id) ||
      !nullableId(row.questionnaire_id) ||
      !nullableId(row.control_id) ||
      !nullableId(row.owner_user_id) ||
      typeof row.owner_missing !== 'boolean' ||
      row.owner_missing !== (row.owner_user_id === null) ||
      (row.reason !== null && typeof row.reason !== 'string') ||
      (row.suggested_evidence_doc_title !== null &&
        typeof row.suggested_evidence_doc_title !== 'string') ||
      !Object.hasOwn(statusLabels, String(row.status)) ||
      !Object.hasOwn(priorityLabels, String(row.priority)) ||
      !Number.isInteger(row.age_days) ||
      Number(row.age_days) < 0 ||
      ids.has(Number(row.id))
    )
      throw new Error('Incomplete gap response')
    ids.add(Number(row.id))
    return row as Gap
  })
}
