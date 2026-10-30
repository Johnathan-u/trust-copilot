'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  ConfirmDialog,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  PartialSuccess,
  ToastNotice,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  mutationFailureNotice,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import {
  listFromPayload,
  loadSection,
  sectionFailure,
} from '@/lib/section-load'
import { pageMode, type FailedSection } from '@/lib/ui-state'

/* ──────────────────── Types ──────────────────── */

type VendorRequest = {
  schema_version: '1'
  workspace_id: number
  delivery_status: string
  expires_at: string | null
  revoked_at: string | null
  submitted_at: string | null
  last_delivery_at: string | null
  last_delivery_error: string | null
  share_url?: string
  id: number
  vendor_email: string
  questionnaire_id: number | null
  message: string | null
  status: string
  link_token: string | null
  created_at: string | null
}

type Questionnaire = {
  id: number
  filename: string
  status: string
}

/* ──────────────────── Helpers ──────────────────── */

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  pending: { label: 'Pending', color: 'bg-amber-500/15 text-amber-400' },
  in_progress: { label: 'In Progress', color: 'bg-blue-500/15 text-blue-400' },
  expired: { label: 'Expired', color: 'bg-tc-surface-raised text-tc-muted' },
  revoked: { label: 'Revoked', color: 'bg-tc-surface-raised text-tc-muted' },
  completed: {
    label: 'Completed',
    color: 'bg-emerald-500/15 text-emerald-400',
  },
}

function statusBadge(status: string) {
  const s = STATUS_STYLE[status] ?? {
    label: status,
    color: 'bg-slate-500/15 text-slate-400',
  }
  return (
    <span
      className={`text-[11px] font-semibold uppercase px-2 py-0.5 rounded ${s.color}`}
    >
      {s.label}
    </span>
  )
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

/* ──────────────────── Component ──────────────────── */

const DELIVERY_LABELS: Record<string, string> = {
  not_sent: 'Not sent',
  sending: 'Delivery awaiting confirmation',
  accepted: 'Accepted by email provider',
  uncertain: 'Delivery outcome unknown',
  unavailable: 'Email delivery unavailable',
  unknown: 'No recorded delivery outcome',
}

function readRequest(data: unknown): VendorRequest {
  if (!data || typeof data !== 'object')
    throw new Error('Invalid request response')
  const row = data as VendorRequest
  if (
    row.schema_version !== '1' ||
    !Number.isInteger(row.id) ||
    !Number.isInteger(row.workspace_id) ||
    typeof row.vendor_email !== 'string' ||
    !Object.hasOwn(STATUS_STYLE, row.status) ||
    !Object.hasOwn(DELIVERY_LABELS, row.delivery_status) ||
    ![
      'expires_at',
      'revoked_at',
      'submitted_at',
      'last_delivery_at',
      'created_at',
    ].every(
      (field) =>
        row[field as keyof VendorRequest] === null ||
        typeof row[field as keyof VendorRequest] === 'string'
    )
  )
    throw new Error('Invalid request response')
  if (row.link_token !== null && typeof row.link_token !== 'string')
    throw new Error('Invalid link')
  if (
    row.share_url !== undefined &&
    (typeof row.share_url !== 'string' || !row.link_token)
  )
    throw new Error('Invalid link')
  if (row.share_url) {
    const url = new URL(row.share_url, window.location.origin)
    if (
      url.origin !== window.location.origin ||
      url.pathname !== '/vendor-response' ||
      url.searchParams.get('token') !== row.link_token
    )
      throw new Error('Invalid link')
  }
  return row
}

function currentStatus(row: VendorRequest) {
  if (row.submitted_at) return 'completed'
  if (row.revoked_at) return 'revoked'
  return row.status === 'completed' ? 'pending' : row.status
}

export default function RequestsPage() {
  const { workspace, permissions } = useAuth()
  return (
    <WorkspaceRequests
      key={`${workspace?.id ?? ''}:${permissions.can_review}:${permissions.can_admin}`}
      workspaceId={workspace?.id}
      canReview={permissions.can_review}
      canAdmin={permissions.can_admin}
    />
  )
}

function WorkspaceRequests({
  workspaceId,
  canReview,
  canAdmin,
}: {
  workspaceId?: number
  canReview: boolean
  canAdmin: boolean
}) {
  const [requests, setRequests] = useState<VendorRequest[]>([])
  const [questionnaires, setQuestionnaires] = useState<Questionnaire[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [partialFailed, setPartialFailed] = useState<FailedSection[]>([])
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [toast, setToast] = useState<{
    message: string
    type: 'success' | 'error'
  } | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [qnrId, setQnrId] = useState('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [invitationBusy, setInvitationBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<VendorRequest | null>(null)
  const [resultKind, setResultKind] = useState<'create' | 'invitation'>(
    'create'
  )
  const [copied, setCopied] = useState(false)
  const [pending, setPending] = useState<Record<number, boolean>>({})
  const [actionErrors, setActionErrors] = useState<Record<number, string>>({})
  const [revokeTarget, setRevokeTarget] = useState<VendorRequest | null>(null)
  const alive = useRef(true)
  const activeWrites = useRef(new Set<string>())
  // One-time links share one result dialog. Claim synchronously before any
  // request, and retain the claim until its displayed result is acknowledged.
  const invitationPhase = useRef<'pending' | 'result' | null>(null)
  const retryKeys = useRef(new Map<string, string>())
  const createAttempt = useRef<{ fingerprint: string; key: string } | null>(
    null
  )
  const readEpoch = useRef(0)
  const copyEpoch = useRef(0)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    if (!canReview || !workspaceId) return
    const epoch = ++readEpoch.current
    const controller = new AbortController()
    const options = {
      credentials: 'include' as const,
      signal: controller.signal,
    }
    const requestPromise = loadSection(
      fetch('/api/vendor-requests', options),
      (data) =>
        listFromPayload<unknown>(data, ['items', 'requests'])
          .map(readRequest)
          .map((row) => {
            if (row.workspace_id !== workspaceId)
              throw new Error('Invalid workspace')
            return row
          })
    )
    const questionnairePromise = loadSection(
      fetch(`/api/questionnaires?workspace_id=${workspaceId}`, options),
      (data) =>
        listFromPayload<Questionnaire>(data, ['items', 'questionnaires'])
    )
    void Promise.all([requestPromise, questionnairePromise]).then(
      ([requestResult, questionnaireResult]) => {
        if (
          !alive.current ||
          controller.signal.aborted ||
          epoch !== readEpoch.current
        )
          return
        const snapshots = [
          {
            id: 'requests',
            label: 'Requests',
            phase: requestResult.ok
              ? requestResult.data.length
                ? ('ready' as const)
                : ('empty' as const)
              : ('error' as const),
            failure: sectionFailure(requestResult),
          },
          {
            id: 'questionnaires',
            label: 'Questionnaires',
            phase: questionnaireResult.ok
              ? questionnaireResult.data.length
                ? ('ready' as const)
                : ('empty' as const)
              : ('error' as const),
            failure: sectionFailure(questionnaireResult),
          },
        ]
        const mode = pageMode(snapshots[0], snapshots.slice(1))
        setRequests(requestResult.ok ? requestResult.data : [])
        setQuestionnaires(
          questionnaireResult.ok ? questionnaireResult.data : []
        )
        setLoadFailure(mode.mode === 'error' ? mode.failure : null)
        setPartialFailed(mode.mode === 'partial' ? mode.failed : [])
        setLoading(false)
      }
    )
    return () => {
      controller.abort()
    }
  }, [workspaceId, canReview, loadAttempt])

  const load = () => {
    setLoading(true)
    setLoadFailure(null)
    setLoadAttempt((value) => value + 1)
  }

  if (!canReview)
    return (
      <div className="min-w-0 space-y-6">
        <h1 className="text-2xl font-bold text-tc-text">Requests</h1>
        <p className="text-sm text-tc-muted">
          You need review access to view requests.
        </p>
      </div>
    )

  const onCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canAdmin || invitationPhase.current) return
    const body = {
      vendor_email: email.trim(),
      ...(qnrId ? { questionnaire_id: Number(qnrId) } : {}),
      ...(message.trim() ? { message: message.trim() } : {}),
    }
    const fingerprint = JSON.stringify(body)
    if (createAttempt.current?.fingerprint !== fingerprint)
      createAttempt.current = { fingerprint, key: crypto.randomUUID() }
    activeWrites.current.add('create')
    invitationPhase.current = 'pending'
    setInvitationBusy(true)
    setSubmitting(true)
    setError(null)
    let resultDisplayed = false
    try {
      const response = await fetch('/api/vendor-requests', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': createAttempt.current.key,
        },
        body: fingerprint,
      })
      const data: unknown = await response.json().catch(() => null)
      if (!alive.current) return
      if (!response.ok) {
        setError(
          mutationFailureNotice(
            response.status,
            data,
            'The request was not created. Try again.'
          ).message
        )
        return
      }
      const row = readRequest(data)
      if (row.workspace_id !== workspaceId) throw new Error('Invalid workspace')
      createAttempt.current = null
      copyEpoch.current++
      invitationPhase.current = 'result'
      setCreated(row)
      setResultKind('create')
      resultDisplayed = true
      load()
    } catch {
      if (alive.current)
        setError(
          'Creation could not be confirmed. Retry the same details to check this request.'
        )
    } finally {
      activeWrites.current.delete('create')
      if (alive.current) {
        setSubmitting(false)
        if (!resultDisplayed) {
          invitationPhase.current = null
          setInvitationBusy(false)
        }
      }
    }
  }

  const resetForm = () => {
    if (invitationPhase.current === 'pending') return
    invitationPhase.current = null
    setInvitationBusy(false)
    copyEpoch.current++
    setCreateOpen(false)
    setEmail('')
    setQnrId('')
    setMessage('')
    setError(null)
    setCreated(null)
    setCopied(false)
    setResultKind('create')
  }

  const copyLink = async (url: string) => {
    const epoch = ++copyEpoch.current
    try {
      const target = new URL(url, window.location.origin)
      if (
        target.origin !== window.location.origin ||
        target.pathname !== '/vendor-response'
      )
        throw new Error('Invalid link')
      await navigator.clipboard.writeText(target.href)
      if (alive.current && epoch === copyEpoch.current) setCopied(true)
    } catch {
      if (alive.current && epoch === copyEpoch.current)
        setToast({
          message: 'The link could not be copied. Try again.',
          type: 'error',
        })
    }
  }

  const mutate = async (
    row: VendorRequest,
    action: 'progress' | 'send' | 'resend' | 'revoke',
    status?: string
  ) => {
    const resource = String(row.id)
    const invitation = action === 'send' || action === 'resend'
    if (
      !canAdmin ||
      activeWrites.current.has(resource) ||
      (invitation && invitationPhase.current)
    )
      return
    if (invitation) {
      invitationPhase.current = 'pending'
      setInvitationBusy(true)
    }
    activeWrites.current.add(resource)
    setPending((current) => ({ ...current, [row.id]: true }))
    setActionErrors((current) => ({ ...current, [row.id]: '' }))
    const operation = `${row.id}:${action}`
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (invitation) {
      if (!retryKeys.current.has(operation))
        retryKeys.current.set(operation, crypto.randomUUID())
      headers['Idempotency-Key'] = retryKeys.current.get(operation)!
    }
    let resultDisplayed = false
    try {
      const response = await fetch(
        `/api/vendor-requests/${row.id}${action === 'progress' ? '' : `/${action}`}`,
        {
          method: action === 'progress' ? 'PATCH' : 'POST',
          credentials: 'include',
          headers,
          ...(action === 'progress'
            ? { body: JSON.stringify({ status }) }
            : {}),
        }
      )
      const data: unknown = await response.json().catch(() => null)
      if (!alive.current) return
      if (!response.ok) {
        setActionErrors((current) => ({
          ...current,
          [row.id]: mutationFailureNotice(
            response.status,
            data,
            'The change was not confirmed. Try again.'
          ).message,
        }))
        return
      }
      const updated = readRequest(data)
      if (updated.id !== row.id || updated.workspace_id !== workspaceId)
        throw new Error('Invalid request')
      readEpoch.current++
      retryKeys.current.delete(operation)
      setRequests((current) =>
        current.map((item) => (item.id === row.id ? updated : item))
      )
      if (invitation && updated.share_url) {
        copyEpoch.current++
        invitationPhase.current = 'result'
        setCreated(updated)
        setResultKind('invitation')
        setCreateOpen(true)
        setCopied(false)
        resultDisplayed = true
      }
      if (action === 'revoke') setRevokeTarget(null)
    } catch {
      if (alive.current)
        setActionErrors((current) => ({
          ...current,
          [row.id]:
            'The result could not be confirmed. Retry the same action to check its outcome.',
        }))
    } finally {
      activeWrites.current.delete(resource)
      if (alive.current) {
        if (invitation && !resultDisplayed) {
          invitationPhase.current = null
          setInvitationBusy(false)
        }
        setPending((current) => ({ ...current, [row.id]: false }))
        if (action === 'revoke') setRevokeTarget(null)
      }
    }
  }

  const qnrName = (id: number | null) => {
    if (!id) return 'General request'
    return (
      questionnaires.find((q) => q.id === id)?.filename ??
      'Questionnaire unavailable'
    )
  }

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Requests</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)] max-w-xl">
            Send a questionnaire or information request to a vendor and collect
            responses securely.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            onClick={load}
            disabled={loading || Object.values(pending).some(Boolean)}
            aria-label="Refresh requests"
          >
            Refresh
          </Button>
          {canAdmin && (
            <Button
              disabled={invitationBusy || Object.values(pending).some(Boolean)}
              onClick={() => {
                if (!invitationPhase.current) setCreateOpen(true)
              }}
            >
              Create Request
            </Button>
          )}
        </div>
      </div>

      {/* Requests table */}
      <Card className="p-0 overflow-hidden">
        {loadFailure ? (
          <div className="p-6">
            <ErrorState failure={loadFailure} onRetry={load} />
          </div>
        ) : loading ? (
          <LoadingState
            label="Loading requests"
            resetKey={loadAttempt}
            onRetry={load}
          >
            <p className="p-6 text-center text-tc-label text-tc-muted">
              Loading requests
            </p>
          </LoadingState>
        ) : (
          <>
            {partialFailed.length > 0 ? (
              <PartialSuccess failed={partialFailed} onRetry={load} />
            ) : null}
            {requests.length === 0 ? (
              <div className="p-10 text-center">
                <div className="text-3xl mb-3">📨</div>
                <p className="text-sm font-medium text-[var(--tc-text)]">
                  No requests yet
                </p>
                <p className="text-xs text-[var(--tc-muted)] mt-1 max-w-sm mx-auto">
                  Create a request to send a questionnaire or information
                  request to a vendor. You will get a secure link to share.
                </p>
                {canAdmin && (
                  <Button
                    className="mt-4"
                    size="sm"
                    disabled={invitationBusy}
                    onClick={() => {
                      if (!invitationPhase.current) setCreateOpen(true)
                    }}
                  >
                    Create First Request
                  </Button>
                )}
              </div>
            ) : (
              <div
                className="overflow-x-auto"
                role="region"
                aria-label="Outbound requests"
                tabIndex={0}
              >
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[var(--tc-border)] text-[10px] uppercase tracking-wider text-[var(--tc-muted)]">
                      <th className="px-5 py-3 text-left font-semibold">
                        Vendor
                      </th>
                      <th className="px-5 py-3 text-left font-semibold">
                        Questionnaire
                      </th>
                      <th className="px-5 py-3 text-left font-semibold">
                        Status
                      </th>
                      <th className="px-5 py-3 text-left font-semibold">
                        Created
                      </th>
                      <th className="px-5 py-3 text-right font-semibold">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((req) => {
                      const status = currentStatus(req)
                      const terminal =
                        status === 'completed' || status === 'revoked'
                      const uncertain =
                        req.delivery_status === 'sending' ||
                        req.delivery_status === 'uncertain'
                      return (
                        <tr
                          key={req.id}
                          className="border-b border-[var(--tc-border)] last:border-0 hover:bg-white/[0.02] transition"
                        >
                          <td className="px-5 py-3">
                            <span className="text-[var(--tc-text)] font-medium break-all">
                              {req.vendor_email}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-[var(--tc-muted)] break-words max-w-xs">
                            {qnrName(req.questionnaire_id)}
                          </td>
                          <td className="px-5 py-3 min-w-48">
                            {statusBadge(status)}
                            <p className="mt-2 text-xs text-tc-muted">
                              {DELIVERY_LABELS[req.delivery_status]}
                            </p>
                            <p className="mt-1 text-xs text-tc-muted">
                              {req.expires_at
                                ? `Link expires ${new Date(req.expires_at).toLocaleDateString()}`
                                : 'Expiry not recorded'}
                            </p>
                            {req.submitted_at && (
                              <p className="mt-1 text-xs text-tc-muted">
                                Response submitted{' '}
                                {new Date(
                                  req.submitted_at
                                ).toLocaleDateString()}
                              </p>
                            )}
                            {uncertain && (
                              <p className="mt-1 text-xs text-tc-muted">
                                Reconcile the previous delivery before sending
                                again.
                              </p>
                            )}
                          </td>
                          <td className="px-5 py-3 text-[var(--tc-muted)] text-xs">
                            {timeAgo(req.created_at)}
                          </td>
                          <td className="px-5 py-3">
                            <div className="flex flex-wrap items-center justify-end gap-2 min-w-44">
                              {canAdmin && !terminal && !uncertain && (
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  disabled={pending[req.id] || invitationBusy}
                                  onClick={() =>
                                    void mutate(
                                      req,
                                      req.delivery_status === 'accepted'
                                        ? 'resend'
                                        : 'send'
                                    )
                                  }
                                >
                                  {req.delivery_status === 'accepted'
                                    ? 'Resend invitation'
                                    : 'Send invitation'}
                                </Button>
                              )}
                              {canAdmin && !terminal && (
                                <>
                                  {status !== 'expired' && (
                                    <select
                                      value=""
                                      disabled={pending[req.id]}
                                      aria-label={`Update progress for ${req.vendor_email}`}
                                      onChange={(event) => {
                                        if (event.target.value)
                                          void mutate(
                                            req,
                                            'progress',
                                            event.target.value
                                          )
                                      }}
                                      className="text-xs rounded border border-tc-border-strong bg-tc-surface-overlay text-tc-text px-2 py-2"
                                    >
                                      <option value="">Update...</option>
                                      {status !== 'in_progress' && (
                                        <option value="in_progress">
                                          In Progress
                                        </option>
                                      )}
                                      {status !== 'pending' && (
                                        <option value="pending">Pending</option>
                                      )}
                                    </select>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    disabled={pending[req.id]}
                                    onClick={() => setRevokeTarget(req)}
                                  >
                                    Revoke link
                                  </Button>
                                </>
                              )}
                            </div>
                            {pending[req.id] && (
                              <p
                                role="status"
                                className="mt-2 text-xs text-tc-muted"
                              >
                                Waiting for acknowledgment…
                              </p>
                            )}
                            {canAdmin && !terminal && !uncertain && (
                              <p className="mt-2 text-xs text-tc-muted">
                                Sending issues a new link and replaces any
                                previous link.
                              </p>
                            )}
                            {actionErrors[req.id] && (
                              <p
                                role="alert"
                                className="mt-2 text-xs text-tc-danger"
                              >
                                {actionErrors[req.id]}
                              </p>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Card>

      {/* Create Request Modal */}
      <Modal
        isOpen={createOpen}
        title={
          created
            ? resultKind === 'create'
              ? 'Request Created'
              : 'Invitation result'
            : 'Create Request'
        }
        closeDisabled={submitting || (invitationBusy && !created)}
        onClose={resetForm}
      >
        {created ? (
          <div className="space-y-4">
            <p className="text-sm text-tc-text">
              {resultKind === 'create'
                ? 'Your request has been created.'
                : DELIVERY_LABELS[created.delivery_status]}
            </p>
            {created.share_url ? (
              <>
                <p className="text-sm text-tc-muted">
                  Copy this one-time secure link now. Later list reads do not
                  return it.
                </p>
                <div className="flex flex-wrap items-center gap-2 p-3 rounded-lg bg-tc-surface-raised border border-tc-border">
                  <code className="min-w-0 flex-1 text-xs text-tc-text break-all">
                    {new URL(created.share_url, window.location.origin).href}
                  </code>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void copyLink(created.share_url!)}
                  >
                    {copied ? 'Copied!' : 'Copy'}
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-sm text-tc-muted">
                The one-time link is not available on this response. The request
                is saved; its delivery state is shown in the list.
              </p>
            )}
            <div className="flex justify-end">
              <Button onClick={resetForm}>Done</Button>
            </div>
          </div>
        ) : (
          <form onSubmit={onCreate} className="space-y-4">
            <div>
              <label
                htmlFor="vendor-email"
                className="block text-xs font-medium text-[var(--tc-muted)] mb-1"
              >
                Vendor Email <span className="text-red-400">*</span>
              </label>
              <Input
                id="vendor-email"
                maxLength={255}
                disabled={submitting}
                type="email"
                placeholder="vendor@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div>
              <label
                htmlFor="vendor-questionnaire"
                className="block text-xs font-medium text-[var(--tc-muted)] mb-1"
              >
                Questionnaire
              </label>
              <select
                id="vendor-questionnaire"
                disabled={submitting}
                value={qnrId}
                onChange={(e) => setQnrId(e.target.value)}
                className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
              >
                <option value="">No questionnaire (general request)</option>
                {questionnaires
                  .filter((q) => q.status === 'completed')
                  .map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.filename}
                    </option>
                  ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="vendor-message"
                className="block text-xs font-medium text-[var(--tc-muted)] mb-1"
              >
                Message{' '}
                <span className="text-[var(--tc-muted)]">(optional)</span>
              </label>
              <textarea
                id="vendor-message"
                disabled={submitting}
                maxLength={10000}
                placeholder="Add context or instructions for the vendor..."
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={3}
                className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] resize-none focus:border-[var(--tc-primary)] focus:outline-none"
              />
            </div>

            {error && (
              <p role="alert" className="text-xs text-tc-danger">
                {error}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="secondary"
                disabled={submitting}
                onClick={resetForm}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Creating...' : 'Create Link'}
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke vendor link?"
        description="The vendor will no longer be able to use this invitation link."
        confirmLabel="Revoke link"
        busy={revokeTarget ? pending[revokeTarget.id] : false}
        onClose={() => setRevokeTarget(null)}
        onConfirm={() => {
          if (revokeTarget) void mutate(revokeTarget, 'revoke')
        }}
      />
      {toast && (
        <ToastNotice
          title={toast.type === 'success' ? 'Success' : 'Error'}
          message={toast.message}
          type={toast.type}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}
