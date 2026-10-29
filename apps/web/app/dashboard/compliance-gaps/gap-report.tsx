'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/ui'
import type { ApiFailurePresentation } from '@/lib/api-error'
import {
  failureOf,
  readSectionJson,
  recordFromPayload,
} from '@/lib/section-load'

export function useSnapshot<T>(url: string, parse: (input: unknown) => T) {
  const [snapshot, setSnapshot] = useState<{
    data: T | null
    fetchedAt: string | null
    failure: ApiFailurePresentation | null
  }>({ data: null, fetchedAt: null, failure: null })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let request: AbortController | null = null
    let timeout: ReturnType<typeof setTimeout> | null = null
    async function refresh() {
      request?.abort()
      if (timeout) clearTimeout(timeout)
      const current = new AbortController()
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
          request === current
        ) {
          setSnapshot({ data: null, fetchedAt: null, failure: null })
        }
        const data = parse(await readSectionJson(response))
        if (active && request === current)
          setSnapshot({
            data,
            fetchedAt: new Date().toISOString(),
            failure: null,
          })
      } catch (error) {
        if (active && request === current)
          setSnapshot((previous) => ({
            ...previous,
            failure: failureOf(error),
          }))
      } finally {
        if (request === current && timeout) clearTimeout(timeout)
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
  }, [url, parse, attempt])
  return { ...snapshot, retry: () => setAttempt((value) => value + 1) }
}

type Gap = {
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
const statusLabels = {
  open: 'Open',
  accepted: 'Accepted',
  dismissed: 'Dismissed',
  resolved: 'Resolved',
}
const priorityLabels = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  settled: 'Settled',
}
function positiveId(value: unknown) {
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

export function EvidenceGapList({ canExport }: { canExport: boolean }) {
  const result = useSnapshot('/api/evidence-gaps', parseGaps)
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
          Review missing evidence, priority, and ownership. This report is
          read-only.
        </p>
      </div>
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
