'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/ui'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { failureOf, readSectionJson } from '@/lib/section-load'

import { GapActionDialog, type GapIntent } from './gap-actions'
import {
  parseGaps,
  statusLabels,
  priorityLabels,
  type Gap,
} from './gap-contract'
export { parseGaps } from './gap-contract'

export function useSnapshot<T>(
  url: string,
  parse: (input: unknown) => T,
  onAccessLost?: () => void
) {
  const [snapshot, setSnapshot] = useState<{
    data: T | null
    fetchedAt: string | null
    failure: ApiFailurePresentation | null
  }>({ data: null, fetchedAt: null, failure: null })
  const [attempt, setAttempt] = useState(0)
  const generation = useRef(0)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => {
    let active = true
    let request: AbortController | null = null
    let timeout: ReturnType<typeof setTimeout> | null = null
    async function refresh() {
      request?.abort()
      if (timeout) clearTimeout(timeout)
      const version = ++generation.current
      const current = new AbortController()
      pending.current = current
      request = current
      timeout = setTimeout(() => current.abort(), 15000)
      try {
        const response = await fetch(url, {
          credentials: 'include',
          signal: current.signal,
        })
        if (
          [401, 403, 404].includes(response.status) &&
          active &&
          request === current &&
          generation.current === version
        ) {
          onAccessLost?.()
          setSnapshot({ data: null, fetchedAt: null, failure: null })
        }
        const data = parse(await readSectionJson(response))
        if (active && request === current && generation.current === version)
          setSnapshot({
            data,
            fetchedAt: new Date().toISOString(),
            failure: null,
          })
      } catch (error) {
        if (active && request === current && generation.current === version)
          setSnapshot((previous) => ({
            ...previous,
            failure: failureOf(error),
          }))
      } finally {
        if (request === current && generation.current === version && timeout)
          clearTimeout(timeout)
      }
    }
    void refresh()
    const timer = setInterval(() => {
      if (!document.hidden) void refresh()
    }, 60000)
    const visible = () => {
      if (!document.hidden) void refresh()
    }
    document.addEventListener('visibilitychange', visible)
    return () => {
      active = false
      request?.abort()
      if (timeout) clearTimeout(timeout)
      clearInterval(timer)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [url, parse, attempt, onAccessLost])
  const apply = useCallback((update: (data: T) => T) => {
    // A pre-mutation read must not replace an acknowledged write.
    generation.current++
    pending.current?.abort()
    setSnapshot((previous) => ({
      ...previous,
      data: previous.data === null ? null : update(previous.data),
    }))
  }, [])
  return { ...snapshot, apply, retry: () => setAttempt((value) => value + 1) }
}

const fieldClass =
  'min-h-11 w-full rounded-tc border border-tc-border-strong bg-tc-surface px-3 text-tc-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-tc-primary'
const titleOf = (gap: Gap) =>
  gap.suggested_evidence_doc_title ||
  (gap.control_id ? 'Control evidence gap' : 'Questionnaire evidence gap')
export function gapCsv(gaps: Gap[], fetchedAt: string) {
  const escape = (value: string | number) => {
    const cell = String(value)
    return `"${(/^[\s]*[=+@-]/.test(cell) ? "'" + cell : cell).replaceAll('"', '""')}"`
  }
  return [
    ['Snapshot retrieved', fetchedAt],
    ['Scope', 'Displayed filtered evidence gaps'],
    ['Rows', gaps.length],
    ['Title', 'Reason', 'Status', 'Priority', 'Age in days', 'Owner'],
    ...gaps.map((gap) => [
      titleOf(gap),
      gap.reason || 'No further reason was provided.',
      statusLabels[gap.status],
      priorityLabels[gap.priority],
      gap.age_days,
      gap.owner_missing ? 'Unassigned' : 'Assigned member',
    ]),
  ]
    .map((row) => row.map(escape).join(','))
    .join('\r\n')
}

export function SnapshotNote({
  fetchedAt,
  failure,
  retry,
}: {
  fetchedAt: string | null
  failure: ApiFailurePresentation | null
  retry: () => void
}) {
  return (
    <div className="space-y-2 text-tc-label text-tc-muted">
      {fetchedAt ? (
        <p>
          Snapshot retrieved{' '}
          <time dateTime={fetchedAt}>
            {new Date(fetchedAt).toLocaleString()}
          </time>
          . Refreshes each minute while this page is visible.
        </p>
      ) : null}
      {failure ? (
        <div role="status">
          <p className="text-tc-text">
            Showing saved snapshot: refresh failed.
          </p>
          <p>{failure.description}</p>
          <Button variant="secondary" onClick={retry}>
            Retry refresh
          </Button>
        </div>
      ) : null}
    </div>
  )
}

export function EvidenceGapList({
  canExport,
  canAdmin,
}: {
  canExport: boolean
  canAdmin: boolean
}) {
  const [action, setAction] = useState<{
    gap: Gap
    kind: GapIntent['kind']
  } | null>(null)
  const [notice, setNotice] = useState<{ message: string } | null>(null)
  const clearPrivateState = useCallback(() => {
    setAction(null)
    setNotice(null)
  }, [])
  const result = useSnapshot('/api/evidence-gaps', parseGaps, clearPrivateState)
  const noticeRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (notice) noticeRef.current?.focus()
  }, [notice])
  const [status, setStatus] = useState('all')
  const [priority, setPriority] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const filtered = (result.data ?? []).filter(
    (gap) =>
      (status === 'all' || gap.status === status) &&
      (priority === 'all' || gap.priority === priority) &&
      `${titleOf(gap)} ${gap.reason ?? ''}`
        .toLowerCase()
        .includes(search.trim().toLowerCase())
  )
  const pages = Math.max(1, Math.ceil(filtered.length / 25))
  const currentPage = Math.min(page, pages)
  const displayed = filtered.slice((currentPage - 1) * 25, currentPage * 25)
  function exportRows() {
    if (!canExport || !result.fetchedAt) return
    const url = URL.createObjectURL(
      new Blob([gapCsv(filtered, result.fetchedAt)], {
        type: 'text/csv;charset=utf-8',
      })
    )
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'evidence-gaps.csv'
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
  }
  return (
    <section aria-labelledby="evidence-gaps-title" className="space-y-4">
      <div>
        <h2
          id="evidence-gaps-title"
          className="text-tc-title font-semibold text-tc-text"
        >
          Evidence gaps
        </h2>
        <p className="text-tc-body text-tc-muted">
          Review missing evidence, priority, and ownership. Resolve open gaps
          with qualifying evidence. Administrators can also accept or dismiss a
          gap.
        </p>
      </div>
      {notice ? (
        <p
          ref={noticeRef}
          tabIndex={-1}
          role="status"
          className="text-tc-body text-tc-text"
        >
          {notice.message}
        </p>
      ) : null}
      {action && result.data ? (
        <GapActionDialog
          key={`${action.gap.id}:${action.kind}`}
          gap={
            result.data.find((gap) => gap.id === action.gap.id) ?? action.gap
          }
          kind={action.kind}
          onClose={() => setAction(null)}
          onConfirmed={(updated, notificationFailed) => {
            result.apply((gaps) =>
              gaps.map((gap) => (gap.id === updated.id ? updated : gap))
            )
            setNotice({
              message: `${titleOf(updated)}: ${statusLabels[updated.status].toLowerCase()} confirmed.${notificationFailed ? ' The gap is resolved, but notification delivery failed.' : ''}`,
            })
            setAction(null)
            result.retry()
          }}
        />
      ) : null}
      {!result.data ? (
        result.failure ? (
          <ErrorState failure={result.failure} onRetry={result.retry} />
        ) : (
          <LoadingState label="Loading evidence gaps" onRetry={result.retry} />
        )
      ) : (
        <>
          <SnapshotNote {...result} />
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-tc-label text-tc-text">
              <span id="gap-status-label">Gap status</span>
              <select
                aria-labelledby="gap-status-label"
                className={fieldClass}
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value)
                  setPage(1)
                }}
              >
                <option value="all">All statuses</option>
                {Object.entries(statusLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-tc-label text-tc-text">
              <span id="gap-priority-label">Gap priority</span>
              <select
                aria-labelledby="gap-priority-label"
                className={fieldClass}
                value={priority}
                onChange={(event) => {
                  setPriority(event.target.value)
                  setPage(1)
                }}
              >
                <option value="all">All priorities</option>
                {Object.entries(priorityLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-tc-label text-tc-text">
              Search gaps
              <input
                className={fieldClass}
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  setPage(1)
                }}
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p role="status" className="text-tc-label text-tc-muted">
              {filtered.length} of {result.data.length} gaps match the filters.
            </p>
            <Button variant="secondary" onClick={result.retry}>
              Refresh gaps
            </Button>
            {canExport ? (
              <Button
                variant="secondary"
                disabled={!filtered.length}
                onClick={exportRows}
              >
                Export displayed gaps
              </Button>
            ) : null}
          </div>
          {displayed.length === 0 ? (
            <EmptyState
              title={
                result.data.length ? 'No matching gaps' : 'No evidence gaps'
              }
              description={
                result.data.length
                  ? 'Change the filters to see other gaps.'
                  : 'No gaps were returned for this workspace.'
              }
            />
          ) : (
            <ul className="space-y-3">
              {displayed.map((gap) => (
                <li key={gap.id}>
                  <Card className="space-y-3 p-4">
                    <h3 className="break-words text-tc-body font-semibold text-tc-text">
                      {titleOf(gap)}
                    </h3>
                    <p className="break-words text-tc-label text-tc-muted">
                      {gap.reason || 'No further reason was provided.'}
                    </p>
                    <dl className="grid grid-cols-2 gap-3 text-tc-label sm:grid-cols-4">
                      {[
                        ['Status', statusLabels[gap.status]],
                        ['Priority', priorityLabels[gap.priority]],
                        ['Age', `${gap.age_days} days`],
                        [
                          'Owner',
                          gap.owner_missing ? 'Unassigned' : 'Assigned member',
                        ],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <dt className="text-tc-muted">{label}</dt>
                          <dd className="font-medium text-tc-text">{value}</dd>
                        </div>
                      ))}
                    </dl>
                    {gap.status === 'open' ? (
                      <div
                        className="flex flex-wrap gap-2"
                        role="group"
                        aria-label={`Actions for ${titleOf(gap)}`}
                      >
                        <Button
                          variant="secondary"
                          onClick={() => setAction({ gap, kind: 'resolve' })}
                        >
                          Resolve gap
                        </Button>
                        {canAdmin ? (
                          <>
                            <Button
                              variant="secondary"
                              onClick={() =>
                                setAction({ gap, kind: 'accepted' })
                              }
                            >
                              Accept gap
                            </Button>
                            <Button
                              variant="secondary"
                              onClick={() =>
                                setAction({ gap, kind: 'dismissed' })
                              }
                            >
                              Dismiss gap
                            </Button>
                          </>
                        ) : null}
                      </div>
                    ) : null}
                    {gap.questionnaire_id ? (
                      <Link
                        className="inline-flex min-h-11 items-center text-tc-primary underline"
                        href={`/dashboard/questionnaires/${gap.questionnaire_id}`}
                      >
                        Review questionnaire
                      </Link>
                    ) : (
                      <p className="text-tc-label text-tc-muted">
                        The report does not include a questionnaire source for
                        this gap.
                      </p>
                    )}
                  </Card>
                </li>
              ))}
            </ul>
          )}
          {pages > 1 ? (
            <nav
              aria-label="Evidence gap pages"
              className="flex flex-wrap items-center gap-3"
            >
              <Button
                variant="secondary"
                disabled={currentPage === 1}
                onClick={() => setPage(currentPage - 1)}
              >
                Previous page
              </Button>
              <span className="text-tc-label text-tc-text">
                Page {currentPage} of {pages}
              </span>
              <Button
                variant="secondary"
                disabled={currentPage === pages}
                onClick={() => setPage(currentPage + 1)}
              >
                Next page
              </Button>
            </nav>
          ) : null}
        </>
      )}
    </section>
  )
}
