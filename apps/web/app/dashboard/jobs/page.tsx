'use client'

import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  Button,
  Card,
  ConfirmDialog,
  ErrorState,
  LoadingState,
  Modal,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  presentHttpFailure,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import { failureOf, isAbortError, readSectionJson } from '@/lib/section-load'
import {
  actionFor,
  cursorForWorkspace,
  JOB_KINDS,
  JOB_STATUSES,
  jobsHref,
  objectLink,
  parseJobDetail,
  parseJobHistory,
  type JobAction,
  type JobHistory,
  type SafeJob,
} from '@/lib/job-history-consumer'

function time(value: string | null): string {
  if (!value) return 'Not reported'
  const utc = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  return `${new Date(utc).toLocaleString('en-US', { timeZone: 'UTC' })} UTC`
}
const outcomes = {
  already_applied: 'The result had already been applied.',
  reconciled: 'The existing result was recovered.',
  superseded: 'A newer operation replaced this result.',
}
function JobFacts({ job }: { job: SafeJob }) {
  return (
    <div className="space-y-tc-3 text-tc-label text-tc-text">
      <p className="font-semibold">
        {job.status ? JOB_STATUSES[job.status] : 'Status unavailable'}
      </p>
      <dl className="grid gap-tc-2 sm:grid-cols-2">
        <div>
          <dt className="text-tc-muted">Created</dt>
          <dd>{time(job.createdAt)}</dd>
        </div>
        <div>
          <dt className="text-tc-muted">Completed</dt>
          <dd>{time(job.completedAt)}</dd>
        </div>
        {job.startedAt && (
          <div>
            <dt className="text-tc-muted">Started</dt>
            <dd>{time(job.startedAt)}</dd>
          </div>
        )}
        <div>
          <dt className="text-tc-muted">Attempts</dt>
          <dd>
            {job.attempt ?? 'Not reported'}
            {job.maxAttempts !== null ? ` of ${job.maxAttempts}` : ''}
          </dd>
        </div>
      </dl>
      {job.progress ? (
        <div>
          <p>
            {job.progress.generated} of {job.progress.total} answers generated
          </p>
          {job.progress.total > 0 && (
            <progress
              className="w-full"
              aria-label="Answers generated"
              value={job.progress.generated}
              max={job.progress.total}
            />
          )}
        </div>
      ) : (
        <p className="text-tc-muted">Progress not reported</p>
      )}
      {job.retryScheduled && (
        <p>Automatic retry scheduled: {time(job.nextAttemptAt)}</p>
      )}
      {job.retriesExhausted && <p>Automatic retry limit reached.</p>}
      {job.failureMessage && <p>{job.failureMessage}</p>}
      {job.outcome && <p>{outcomes[job.outcome]}</p>}
      {job.chargeUncertain && (
        <p className="rounded-tc border border-tc-border-strong p-tc-3">
          A previous provider call may have been charged. Review it before
          retrying.
        </p>
      )}
    </div>
  )
}

function JobsForWorkspace({
  workspaceId,
  canAdmin,
  beforeId,
}: {
  workspaceId: number
  canAdmin: boolean
  beforeId: number | null
}) {
  const router = useRouter()
  const [history, setHistory] = useState<JobHistory | null>(null)
  const [failure, setFailure] = useState<ApiFailurePresentation | null>(null)
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<SafeJob | null>(null)
  const [detailFailure, setDetailFailure] =
    useState<ApiFailurePresentation | null>(null)
  const [detailReload, setDetailReload] = useState(0)
  const [confirmation, setConfirmation] = useState<{
    job: SafeJob
    action: JobAction
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionFailure, setActionFailure] =
    useState<ApiFailurePresentation | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [adminDenied, setAdminDenied] = useState(false)
  const allowAdmin = canAdmin && !adminDenied
  const active = useRef(false)
  const historyRequest = useRef<AbortController | null>(null)
  const detailRequest = useRef<AbortController | null>(null)
  const mutation = useRef<AbortController | null>(null)
  const clearPrivateState = useCallback(() => {
    // Invalidate both reads before clearing state: even a late successful reply
    // from the previous authority must not restore rows, links or a dialog.
    historyRequest.current?.abort()
    detailRequest.current?.abort()
    mutation.current?.abort()
    mutation.current = null
    setHistory(null)
    setSelectedId(null)
    setDetail(null)
    setDetailFailure(null)
    setConfirmation(null)
    setNotice(null)
    setActionFailure(null)
    setFailure(null)
    setBusy(false)
    setLoading(false)
  }, [])
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      mutation.current?.abort()
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    historyRequest.current = controller
    void (async () => {
      // Do not send a business read for StrictMode's discarded setup.
      await Promise.resolve()
      if (controller.signal.aborted) return
      try {
        const response = await fetch(
          `/api/jobs?workspace_id=${workspaceId}&limit=25${beforeId === null ? '' : `&before_id=${beforeId}`}`,
          {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          }
        )
        if (
          !controller.signal.aborted &&
          [401, 403, 404].includes(response.status)
        ) {
          clearPrivateState()
          setFailure(presentHttpFailure({ status: response.status }))
          return
        }
        const page = parseJobHistory(await readSectionJson(response), beforeId)
        if (!controller.signal.aborted) setHistory(page)
      } catch (error) {
        if (!controller.signal.aborted && !isAbortError(error))
          setFailure(failureOf(error))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [workspaceId, beforeId, reload, clearPrivateState])
  useEffect(() => {
    if (selectedId === null) return
    const controller = new AbortController()
    detailRequest.current = controller
    void (async () => {
      await Promise.resolve()
      if (controller.signal.aborted) return
      try {
        const response = await fetch(
          `/api/jobs/${selectedId}?workspace_id=${workspaceId}`,
          {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          }
        )
        if (
          !controller.signal.aborted &&
          [401, 403].includes(response.status)
        ) {
          clearPrivateState()
          setFailure(presentHttpFailure({ status: response.status }))
          return
        }
        const job = parseJobDetail(await readSectionJson(response), selectedId)
        if (!controller.signal.aborted) setDetail(job)
      } catch (error) {
        if (!controller.signal.aborted && !isAbortError(error))
          setDetailFailure(failureOf(error))
      }
    })()
    return () => controller.abort()
  }, [workspaceId, selectedId, detailReload, clearPrivateState])
  async function confirmAction() {
    if (
      !confirmation ||
      mutation.current ||
      !allowAdmin ||
      actionFor(confirmation.job, allowAdmin) !== confirmation.action
    )
      return
    const { job, action } = confirmation
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true)
    setActionFailure(null)
    setNotice(null)
    try {
      const response = await fetch(
        `/api/jobs/${job.id}/${action}?workspace_id=${workspaceId}`,
        { method: 'POST', credentials: 'include', signal: controller.signal }
      )
      if (!active.current || controller.signal.aborted) return
      if (response.status === 401) {
        clearPrivateState()
        setFailure(presentHttpFailure({ status: response.status }))
        return
      }
      if (response.status === 403) {
        // An admin denial does not establish whether review access remains.
        // Restore only newly authorized history, without repeating admin actions.
        clearPrivateState()
        setAdminDenied(true)
        setActionFailure(presentHttpFailure({ status: response.status }))
        setLoading(true)
        setReload((value) => value + 1)
        return
      }
      const ack = parseJobDetail(
        await readSectionJson(response),
        job.id,
        action
      )
      if (!active.current || controller.signal.aborted) return
      // An acknowledgment is required before changing the rendered lifecycle.
      setHistory((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === ack.id ? ack : item
              ),
            }
          : current
      )
      setNotice(
        action === 'cancel' ? 'Job cancelled.' : 'Another attempt is queued.'
      )
      setConfirmation(null)
      setLoading(true)
      setFailure(null)
      setReload((value) => value + 1)
    } catch (error) {
      if (active.current && !controller.signal.aborted) {
        setActionFailure(failureOf(error))
        setConfirmation(null)
      }
    } finally {
      if (active.current && !controller.signal.aborted) {
        mutation.current = null
        setBusy(false)
      }
    }
  }
  const refresh = () => {
    setActionFailure(null)
    setLoading(true)
    setFailure(null)
    setReload((value) => value + 1)
  }
  const refreshDetail = () => {
    setDetail(null)
    setDetailFailure(null)
    setDetailReload((value) => value + 1)
  }
  return (
    <section aria-label="Job history" className="space-y-tc-4">
      <div className="flex flex-wrap items-center justify-between gap-tc-3">
        <p className="text-tc-label text-tc-muted">
          {beforeId === null ? 'Newest jobs first.' : 'Showing older jobs.'}{' '}
          Reload to check for updates.
        </p>
        <Button variant="secondary" onClick={refresh} disabled={busy}>
          Reload jobs
        </Button>
      </div>
      {adminDenied && (
        <p className="text-tc-label text-tc-muted">
          Administrative actions are unavailable for your current access.
        </p>
      )}
      {notice && (
        <p role="status" className="text-tc-label text-tc-text">
          {notice}
        </p>
      )}
      {actionFailure && (
        <div aria-label="Job action failed">
          <ErrorState failure={actionFailure} onRetry={refresh} />
        </div>
      )}
      {failure && (
        <div>
          {history && (
            <p className="mb-tc-2 text-tc-label text-tc-muted">
              The latest history could not be loaded. These are the last
              confirmed results.
            </p>
          )}
          <ErrorState failure={failure} onRetry={refresh} />
        </div>
      )}
      {loading && (
        <LoadingState label="Loading jobs" onRetry={refresh} resetKey={reload}>
          <p className="text-tc-label text-tc-muted">Loading jobs…</p>
        </LoadingState>
      )}
      {history && (
        <>
          {history.items.length === 0 && (
            <Card>
              <h2 className="text-tc-title font-semibold">
                {beforeId === null ? 'No jobs yet' : 'No older jobs'}
              </h2>
              <p className="mt-tc-2 text-tc-label text-tc-muted">
                {beforeId === null
                  ? 'Parsing, indexing, answer generation and exports appear here when they run.'
                  : 'Return to the newest jobs to check recent activity.'}
              </p>
            </Card>
          )}
          <div className="space-y-tc-4">
            {history.items.map((job) => {
              const title = job.kind ? JOB_KINDS[job.kind] : 'Unrecognized job'
              const link = objectLink(job)
              const action = actionFor(job, allowAdmin)
              return (
                <article key={job.id} aria-label={title}>
                  <Card>
                    <h2 className="mb-tc-3 text-tc-title font-semibold text-tc-text">
                      {title}
                    </h2>
                    <JobFacts job={job} />
                    <div className="mt-tc-4 flex flex-wrap items-center gap-tc-3">
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setDetail(null)
                          setDetailFailure(null)
                          setSelectedId(job.id)
                        }}
                      >
                        View details
                      </Button>
                      {link && (
                        <Link
                          className="text-tc-primary underline"
                          href={link.href}
                        >
                          {link.label}
                        </Link>
                      )}
                      {action && (
                        <Button
                          variant={action === 'cancel' ? 'danger' : 'secondary'}
                          disabled={busy || loading || Boolean(failure)}
                          onClick={() => {
                            setActionFailure(null)
                            setNotice(null)
                            setConfirmation({ job, action })
                          }}
                        >
                          {action === 'cancel' ? 'Cancel job' : 'Retry job'}
                        </Button>
                      )}
                    </div>
                  </Card>
                </article>
              )
            })}
          </div>
          <nav
            aria-label="Job history pages"
            className="flex flex-wrap gap-tc-3"
          >
            {beforeId !== null && (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => router.push(jobsHref(workspaceId))}
              >
                Newest jobs
              </Button>
            )}
            {history.nextBeforeId !== null && (
              <Button
                variant="secondary"
                disabled={busy || loading || Boolean(failure)}
                onClick={() =>
                  router.push(jobsHref(workspaceId, history.nextBeforeId))
                }
              >
                Older jobs
              </Button>
            )}
          </nav>
        </>
      )}
      <Modal
        isOpen={selectedId !== null}
        onClose={() => setSelectedId(null)}
        title="Job details"
        description="Current status for this job."
      >
        {detailFailure ? (
          <ErrorState failure={detailFailure} onRetry={refreshDetail} />
        ) : detail ? (
          <>
            <h2 className="mb-tc-3 text-tc-title font-semibold">
              {detail.kind ? JOB_KINDS[detail.kind] : 'Unrecognized job'}
            </h2>
            <JobFacts job={detail} />
            <Button
              className="mt-tc-4"
              variant="secondary"
              onClick={refreshDetail}
            >
              Reload details
            </Button>
          </>
        ) : (
          <LoadingState
            label="Loading job details"
            onRetry={refreshDetail}
            resetKey={detailReload}
          >
            <p>Loading job details…</p>
          </LoadingState>
        )}
      </Modal>
      <ConfirmDialog
        open={confirmation !== null}
        title={
          confirmation?.action === 'cancel'
            ? 'Cancel this job?'
            : 'Retry this job?'
        }
        description={
          confirmation?.action === 'cancel'
            ? 'Stop this job. Work already applied is not undone.'
            : `Queue another attempt.${confirmation?.job.chargeUncertain ? ' A previous provider call may have been charged. Review it before retrying.' : ''}`
        }
        confirmLabel={
          confirmation?.action === 'cancel' ? 'Cancel job' : 'Retry job'
        }
        onClose={() => {
          if (!busy) setConfirmation(null)
        }}
        onConfirm={() => {
          void confirmAction()
        }}
        busy={busy}
      />
    </section>
  )
}

function JobsContent() {
  const { workspace, permissions, loading } = useAuth()
  const params = useSearchParams()
  const router = useRouter()
  let beforeId: number | null = null
  let invalidCursor = false
  if (workspace) {
    try {
      beforeId = cursorForWorkspace(params, workspace.id)
    } catch {
      invalidCursor = true
    }
  }
  return (
    <div className="space-y-tc-6">
      <header>
        <h1 className="text-tc-headline font-semibold text-tc-text">Jobs</h1>
        <p className="mt-tc-2 text-tc-label text-tc-muted">
          Track background work in your current workspace.
        </p>
      </header>
      {loading ? (
        <p role="status">Loading workspace…</p>
      ) : !workspace || !permissions.can_review ? (
        <Card>
          <h2 className="text-tc-title font-semibold">
            Job access is restricted
          </h2>
          <p className="mt-tc-2 text-tc-label text-tc-muted">
            Your current workspace permissions do not allow reviewing jobs.
          </p>
        </Card>
      ) : invalidCursor ? (
        <Card>
          <h2 className="text-tc-title font-semibold">
            This history page is unavailable
          </h2>
          <p className="my-tc-3 text-tc-label">
            The saved page address is invalid. Return to the newest jobs.
          </p>
          <Button onClick={() => router.push(jobsHref(workspace.id))}>
            Newest jobs
          </Button>
        </Card>
      ) : (
        <JobsForWorkspace
          key={`${workspace.id}:${permissions.can_admin}:${beforeId}`}
          workspaceId={workspace.id}
          canAdmin={permissions.can_admin}
          beforeId={beforeId}
        />
      )}
    </div>
  )
}
export default function JobsPage() {
  return (
    <Suspense fallback={<p role="status">Loading jobs…</p>}>
      <JobsContent />
    </Suspense>
  )
}
