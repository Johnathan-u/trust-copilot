import { ApiRequestError, presentHttpFailure } from './api-error'
import { recordFromPayload } from './section-load'

export const JOB_KINDS = {
  parse_questionnaire: 'Parse questionnaire',
  parse_evidence: 'Parse evidence',
  index_document: 'Index document',
  generate_answers: 'Generate answers',
  export: 'Export questionnaire',
} as const
export const JOB_STATUSES = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
} as const
type Kind = keyof typeof JOB_KINDS
type Status = keyof typeof JOB_STATUSES
export type JobAction = 'cancel' | 'retry'
export type SafeJob = {
  id: number
  kind: Kind | null
  status: Status | null
  attempt: number | null
  maxAttempts: number | null
  createdAt: string | null
  startedAt: string | null
  completedAt: string | null
  nextAttemptAt: string | null
  retryScheduled: boolean
  retriesExhausted: boolean
  chargeUncertain: boolean
  failureMessage: string | null
  progress: { generated: number; total: number } | null
  outcome: 'already_applied' | 'reconciled' | 'superseded' | null
  objectRef: { type: 'document' | 'questionnaire'; id: number } | null
}
export type JobHistory = { items: SafeJob[]; nextBeforeId: number | null }
function malformed(): never {
  throw new ApiRequestError(presentHttpFailure({ malformed: true }))
}
function integer(value: unknown, minimum = 0): value is number {
  return (
    typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum
  )
}
function timestamp(value: unknown): string | null {
  return typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.test(
      value
    ) &&
    Number.isFinite(Date.parse(value))
    ? value
    : null
}
function progress(value: unknown): SafeJob['progress'] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const p = value as Record<string, unknown>
  return integer(p.generated) && integer(p.total) && p.generated <= p.total
    ? { generated: p.generated, total: p.total }
    : null
}
function failureMessage(code: unknown): string {
  switch (code) {
    case 'bad_input':
      return 'The input could not be processed. Review the source before retrying.'
    case 'not_found':
      return 'The source is no longer available.'
    case 'auth_failed':
    case 'permission_denied':
    case 'config_error':
    case 'model_credentials_missing':
    case 'model_credentials_invalid':
    case 'model_quota_exhausted':
      return 'An administrator needs to review access or configuration before retrying.'
    case 'rate_limited':
    case 'timeout':
    case 'upstream_unavailable':
    case 'connection_error':
    case 'database_unavailable':
    case 'lease_expired':
    case 'model_rate_limited':
    case 'model_timeout':
    case 'model_server_error':
      return 'A temporary service problem interrupted this job.'
    default:
      return 'This job failed. Review its source and configuration before retrying.'
  }
}
function project(data: unknown, legacy: boolean): SafeJob {
  const r = recordFromPayload(data)
  if (
    !integer(r.id, 1) ||
    !('kind' in r) ||
    !('status' in r) ||
    typeof r.charge_uncertain !== 'boolean'
  )
    malformed()
  const kind =
    typeof r.kind === 'string' && Object.hasOwn(JOB_KINDS, r.kind)
      ? (r.kind as Kind)
      : null
  const status =
    typeof r.status === 'string' && Object.hasOwn(JOB_STATUSES, r.status)
      ? (r.status as Status)
      : null
  const result =
    legacy &&
    r.result &&
    typeof r.result === 'object' &&
    !Array.isArray(r.result)
      ? (r.result as Record<string, unknown>)
      : null
  const rawOutcome = legacy ? result?.outcome : r.outcome
  const outcome =
    rawOutcome === 'already_applied' ||
    rawOutcome === 'reconciled' ||
    rawOutcome === 'superseded'
      ? rawOutcome
      : null
  let objectRef: SafeJob['objectRef'] = null
  if (!legacy && kind && r.object_ref && typeof r.object_ref === 'object') {
    const ref = r.object_ref as Record<string, unknown>
    const type =
      kind === 'index_document' || kind === 'parse_evidence'
        ? 'document'
        : 'questionnaire'
    if (ref.type === type && integer(ref.id, 1) && ref.id <= 2147483647)
      objectRef = { type, id: ref.id }
  }
  return {
    id: r.id as number,
    kind,
    status,
    attempt: integer(r.attempt) ? r.attempt : null,
    maxAttempts:
      integer(r.max_attempts, 1) && r.max_attempts <= 10
        ? r.max_attempts
        : null,
    createdAt: timestamp(r.created_at),
    startedAt: legacy ? null : timestamp(r.started_at),
    completedAt: timestamp(r.completed_at),
    nextAttemptAt: timestamp(r.next_attempt_at),
    retryScheduled: status === 'queued' && r.retry_scheduled === true,
    retriesExhausted: status === 'failed' && r.retries_exhausted === true,
    chargeUncertain: r.charge_uncertain === true,
    failureMessage: status === 'failed' ? failureMessage(r.error_code) : null,
    progress:
      kind === 'generate_answers'
        ? progress(legacy ? result : r.progress)
        : null,
    outcome,
    objectRef,
  }
}
export function parseJobHistory(
  data: unknown,
  beforeId: number | null = null
): JobHistory {
  const r = recordFromPayload(data)
  if (
    !Array.isArray(r.items) ||
    r.items.length > 25 ||
    !('next_before_id' in r)
  )
    malformed()
  const items = (r.items as unknown[]).map((item) => project(item, false))
  if (
    items.some(
      (item, i) =>
        (beforeId !== null && item.id >= beforeId) ||
        (i > 0 && item.id >= items[i - 1].id)
    )
  )
    malformed()
  if (
    r.next_before_id !== null &&
    (!integer(r.next_before_id, 1) || r.next_before_id !== items.at(-1)?.id)
  )
    malformed()
  return { items, nextBeforeId: r.next_before_id as number | null }
}
export function parseJobDetail(
  data: unknown,
  expectedId: number,
  action?: JobAction
): SafeJob {
  const job = project(data, true)
  if (
    job.id !== expectedId ||
    (action && job.status !== (action === 'cancel' ? 'cancelled' : 'queued'))
  )
    malformed()
  return job
}
export function actionFor(job: SafeJob, canAdmin: boolean): JobAction | null {
  if (!canAdmin || !job.kind) return null
  if (job.status === 'queued' || job.status === 'running') return 'cancel'
  if (job.status === 'failed' || job.status === 'cancelled') return 'retry'
  return null
}
export function objectLink(
  job: SafeJob
): { href: string; label: string } | null {
  if (!job.objectRef) return null
  return job.objectRef.type === 'questionnaire'
    ? {
        href: `/dashboard/questionnaires/${job.objectRef.id}`,
        label: 'Open questionnaire',
      }
    : { href: '/dashboard/documents', label: 'Open document library' }
}
export function jobsHref(
  workspaceId: number,
  beforeId: number | null = null
): string {
  return `/dashboard/jobs?workspace_id=${workspaceId}${beforeId === null ? '' : `&before_id=${beforeId}`}`
}
export function cursorForWorkspace(
  params: Pick<URLSearchParams, 'get' | 'getAll'>,
  workspaceId: number
): number | null {
  if (params.get('workspace_id') !== String(workspaceId)) return null
  const raw = params.get('before_id')
  if (raw === null) return null
  if (
    params.getAll('workspace_id').length !== 1 ||
    params.getAll('before_id').length !== 1 ||
    !/^[1-9]\d*$/.test(raw) ||
    !integer(Number(raw), 1)
  )
    malformed()
  return Number(raw)
}
