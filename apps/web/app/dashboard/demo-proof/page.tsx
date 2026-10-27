'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import { Button, Card, EmptyState } from '@/components/ui'
import { presentDemoProof } from '@/lib/demoProofSummary.mjs'

type Presented = ReturnType<typeof presentDemoProof>

function errorMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const record = body as { message?: unknown; detail?: unknown; field_errors?: unknown }
    if (typeof record.message === 'string' && record.message) return record.message
    if (typeof record.detail === 'string' && record.detail) return record.detail
  }
  if (status === 401) return 'Sign in to view this summary.'
  if (status === 403) return 'You do not have access to this workspace summary.'
  return 'The summary could not be loaded.'
}

function windowText(row: { windowStart: string | null; windowEnd: string | null; timezone: string | null }): string {
  if (!row.windowStart && !row.windowEnd) return 'No observation window'
  const zone = row.timezone || 'UTC'
  return `${row.windowStart || 'open'} to ${row.windowEnd || 'open'} (${zone})`
}

export default function DemoProofPage() {
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [presented, setPresented] = useState<Presented | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (windowStart.trim()) params.set('window_start', windowStart.trim())
      if (windowEnd.trim()) params.set('window_end', windowEnd.trim())
      const query = params.toString()
      const response = await fetch(query ? `/api/demo-proof?${query}` : '/api/demo-proof', {
        credentials: 'include',
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        setPresented(null)
        setError(errorMessage(response.status, body))
        return
      }
      const next = presentDemoProof(body)
      setPresented(next)
      if (next.state === 'rejected' || next.state === 'unsupported_schema' || next.state === 'unavailable') {
        setError(next.reason || 'This summary cannot be shown.')
      }
    } catch {
      setPresented(null)
      setError('Network error loading the demonstration summary.')
    } finally {
      setLoading(false)
    }
  }, [windowStart, windowEnd])

  const showRows = presented && presented.rows.length > 0 && !error

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <Link href="/dashboard" className="text-sm text-[var(--tc-muted)] hover:text-[var(--tc-text)]">
          ← Dashboard
        </Link>
      </div>
      <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-1">Demonstration proof</h1>
      <p className="text-sm text-[var(--tc-muted)] mb-2 max-w-2xl">
        Counts are read from records stored in this workspace. A missing source stays unavailable.
        Customers, revenue and traffic are unsupported when no evidence of them is stored.
      </p>
      <p className="text-sm font-medium text-[var(--tc-text)] mb-6">Not commercial traction</p>

      <Card className="mb-6 p-5">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void load()
          }}
        >
          <div className="min-w-[220px] flex-1">
            <label htmlFor="demo-proof-window-start" className="mb-1.5 block text-xs font-medium text-[var(--tc-muted)]">
              Window start (UTC)
            </label>
            <input
              id="demo-proof-window-start"
              value={windowStart}
              onChange={(event) => setWindowStart(event.target.value)}
              placeholder="2026-01-01T00:00:00Z"
              className="w-full rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)]"
            />
          </div>
          <div className="min-w-[220px] flex-1">
            <label htmlFor="demo-proof-window-end" className="mb-1.5 block text-xs font-medium text-[var(--tc-muted)]">
              Window end (UTC)
            </label>
            <input
              id="demo-proof-window-end"
              value={windowEnd}
              onChange={(event) => setWindowEnd(event.target.value)}
              placeholder="2026-02-01T00:00:00Z"
              className="w-full rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)]"
            />
          </div>
          <Button type="submit" loading={loading}>
            Load summary
          </Button>
          <Button type="button" variant="secondary" onClick={() => void load()} disabled={loading}>
            Retry
          </Button>
        </form>
        <p className="mt-3 text-xs text-[var(--tc-muted)]">
          Leave both fields empty to use the span of stored records. Both fields are required together.
        </p>
      </Card>

      {error && (
        <Card className="mb-6 p-5">
          <p role="alert" className="text-sm text-[var(--tc-text)]">{error}</p>
        </Card>
      )}

      {!presented && !error && !loading && (
        <EmptyState
          title="No summary loaded"
          description="Load the workspace summary. An empty workspace is shown as no data, not as a sample result."
        />
      )}

      {presented && presented.status === 'no_data' && (
        <Card className="mb-6 p-5">
          <EmptyState
            title="No data"
            description="No stored records were found for this window. The synthetic sample is not used to fill this summary."
          />
        </Card>
      )}

      {showRows && presented && (
        <Card className="mb-6 p-5">
          <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-1">Stored records</h2>
          <p className="text-sm text-[var(--tc-muted)] mb-4">
            Status: {presented.status}. {presented.tractionLabel}.
            {presented.dataWindow && typeof presented.dataWindow.reason === 'string'
              ? ` ${presented.dataWindow.reason}`
              : ''}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Workspace demonstration counts with origin, basis and data window</caption>
              <thead>
                <tr className="text-[var(--tc-muted)]">
                  <th className="py-2 pr-3 font-medium">Fact</th>
                  <th className="py-2 pr-3 font-medium">Value</th>
                  <th className="py-2 pr-3 font-medium">Origin</th>
                  <th className="py-2 pr-3 font-medium">Basis</th>
                  <th className="py-2 pr-3 font-medium">Data window</th>
                  <th className="py-2 font-medium">Traction</th>
                </tr>
              </thead>
              <tbody>
                {presented.rows.map((row) => (
                  <tr key={row.name} className="border-t border-[var(--tc-border)]">
                    <td className="py-2 pr-3 text-[var(--tc-text)]">{row.name}</td>
                    <td className="py-2 pr-3 text-[var(--tc-text)]">{row.displayValue}</td>
                    <td className="py-2 pr-3 text-[var(--tc-text)]">{row.origin || 'Not identified'}</td>
                    <td className="py-2 pr-3 text-[var(--tc-text)]">{row.basis || 'Not identified'}</td>
                    <td className="py-2 pr-3 text-[var(--tc-text)]">{windowText(row)}</td>
                    <td className="py-2 text-[var(--tc-text)]">{row.tractionLabel}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {presented && presented.partialFailures.length > 0 && (
        <Card className="mb-6 p-5">
          <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-2">Partial failures</h2>
          <ul className="grid gap-2 text-sm text-[var(--tc-text)]">
            {presented.partialFailures.map((failure, index) => (
              <li key={`${String(failure.code)}-${String(failure.source)}-${index}`}>
                {String(failure.message || 'A source could not be included.')}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {presented && presented.unsupported.length > 0 && (
        <Card className="mb-6 p-5">
          <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-2">Unsupported</h2>
          <ul className="grid gap-2 text-sm text-[var(--tc-text)]">
            {presented.unsupported.map((item) => (
              <li key={String(item.name)}>
                <span className="font-medium">{String(item.name)}</span>
                {': '}
                {String(item.displayValue || 'Unsupported')}
                {item.reason ? ` — ${String(item.reason)}` : ''}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {presented && presented.synthetic.length > 0 && (
        <Card className="p-5">
          <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-2">Synthetic placeholder</h2>
          <p className="text-sm text-[var(--tc-muted)] mb-3">
            The sample questionnaire, coverage report, gap list and walkthrough are synthetic
            placeholders. They are not evidence and they are not commercial traction.
          </p>
          <ul className="grid gap-1 text-sm text-[var(--tc-text)]">
            {presented.synthetic.map((item) => (
              <li key={String(item.name)}>
                {String(item.label)}: {String(item.name)} ({String(item.origin)}, {String(item.basis)})
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
