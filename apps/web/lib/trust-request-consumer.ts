/** The existing incoming Trust API, with no storage keys or provider diagnostics. */
export type TrustRequest = {
  id: number
  workspace_id: number
  requester_email: string
  requester_name: string | null
  subject: string | null
  message: string
  status: string
  attachment_filename: string | null
  assignee: string | null
}
export type TrustNote = {
  id: number
  trust_request_id: number
  note_type: 'reply' | 'internal_note'
  body: string
  body_revision: number
  approved_revision: number | null
  approved_by: number | null
  approved_at: string | null
  delivery_status: string | null
  author: string | null
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Invalid response')
  return value as Record<string, unknown>
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid response')
  return value
}
function optionalText(value: unknown): string | null {
  return value == null ? null : text(value)
}
function integer(value: unknown, minimum = 1): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < minimum
  )
    throw new Error('Invalid response')
  return value
}
export function parseTrustRequest(
  value: unknown,
  workspaceId: number,
  requestId?: number
): TrustRequest {
  const r = record(value)
  const id = integer(r.id)
  if (
    r.workspace_id !== workspaceId ||
    (requestId !== undefined && id !== requestId)
  )
    throw new Error('Invalid response')
  return {
    id,
    workspace_id: workspaceId,
    requester_email: text(r.requester_email),
    requester_name: optionalText(r.requester_name),
    subject: optionalText(r.subject),
    message: text(r.message),
    status: text(r.status),
    attachment_filename: optionalText(r.attachment_filename),
    assignee: optionalText(r.assignee_display_name ?? r.assignee_email),
  }
}
export function parseTrustRequests(
  value: unknown,
  workspaceId: number
): TrustRequest[] {
  if (!Array.isArray(value)) throw new Error('Invalid response')
  const rows = value.map((item) => parseTrustRequest(item, workspaceId))
  if (new Set(rows.map((row) => row.id)).size !== rows.length)
    throw new Error('Invalid response')
  return rows
}
export function parseTrustNote(
  value: unknown,
  requestId: number,
  noteId?: number
): TrustNote {
  const r = record(value)
  const id = integer(r.id)
  if (
    r.trust_request_id !== requestId ||
    (noteId !== undefined && id !== noteId)
  )
    throw new Error('Invalid response')
  if (r.note_type !== 'reply' && r.note_type !== 'internal_note')
    throw new Error('Invalid response')
  return {
    id,
    trust_request_id: requestId,
    note_type: r.note_type,
    body: text(r.body),
    body_revision: r.body_revision == null ? 0 : integer(r.body_revision, 0),
    approved_revision:
      r.approved_revision == null ? null : integer(r.approved_revision, 0),
    approved_by: r.approved_by == null ? null : integer(r.approved_by),
    approved_at: optionalText(r.approved_at),
    delivery_status: optionalText(r.delivery_status),
    author: optionalText(r.author_display_name ?? r.author_email),
  }
}
export function parseTrustNotes(
  value: unknown,
  requestId: number
): TrustNote[] {
  if (!Array.isArray(value)) throw new Error('Invalid response')
  const rows = value.map((item) => parseTrustNote(item, requestId))
  if (new Set(rows.map((row) => row.id)).size !== rows.length)
    throw new Error('Invalid response')
  return rows
}
export function replyActions(note: TrustNote) {
  const editable =
    note.note_type === 'reply' &&
    (note.delivery_status === null ||
      ['draft', 'approved', 'unavailable'].includes(note.delivery_status))
  const approved =
    note.body_revision > 0 &&
    note.approved_revision === note.body_revision &&
    note.approved_by !== null &&
    note.approved_at !== null &&
    Number.isFinite(Date.parse(note.approved_at))
  return {
    edit: editable,
    approve: editable && note.body_revision > 0 && !approved,
    send:
      editable &&
      approved &&
      ['approved', 'unavailable'].includes(note.delivery_status ?? ''),
  }
}
export function deliveryLabel(status: string | null): string {
  switch (status) {
    case 'draft':
      return 'Draft — approval required'
    case 'approved':
      return 'Approved — not sent'
    case 'accepted':
      return 'Provider accepted — recipient delivery not confirmed'
    case 'uncertain':
      return 'Delivery outcome unknown — do not resend'
    case 'sending':
      return 'Sending recorded — outcome pending; do not resend'
    case 'unavailable':
      return 'Delivery unavailable — provider was not called'
    default:
      return 'Unknown approval or delivery history'
  }
}
export function trustFailure(status: number): string {
  if (status === 403)
    return 'You do not have permission for this action. Your text is kept here.'
  if (status === 404)
    return 'This request or reply is unavailable. Your text is kept here.'
  if (status === 409)
    return 'The saved reply or its state changed. Reload saved replies and review the current revision. Your text is kept here.'
  if (status === 422)
    return 'Check the reply text and try again. Your text is kept here.'
  return 'The result was not confirmed. Reload saved replies before another action. Your text is kept here.'
}
export class TrustApiError extends Error {
  constructor(readonly status: number) {
    super(trustFailure(status))
  }
}
export async function trustFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const signal = init.signal
    ? AbortSignal.any([init.signal, AbortSignal.timeout(15000)])
    : AbortSignal.timeout(15000)
  const response = await fetch(`/api/trust-requests${path}`, {
    ...init,
    credentials: 'include',
    cache: 'no-store',
    signal,
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!response.ok) throw new TrustApiError(response.status)
  return response
}
export async function trustJson(
  path: string,
  init: RequestInit = {}
): Promise<unknown> {
  return (await trustFetch(path, init)).json()
}
