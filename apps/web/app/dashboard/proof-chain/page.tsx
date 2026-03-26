'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Button, Card, Input, Skeleton } from '@/components/ui'

type ChainNode = {
  id: number
  node_type: string
  ref_table: string | null
  ref_id: number | null
  label: string | null
  meta_json: string | null
  version: number
  freshness: string
}

type ChainResponse = { answer_id: number; chain: ChainNode[] }

const FRESHNESS_STYLE: Record<string, { bg: string; border: string; label: string }> = {
  live: {
    bg: 'rgba(34, 197, 94, 0.12)',
    border: 'rgba(34, 197, 94, 0.35)',
    label: 'Live',
  },
  recent: {
    bg: 'rgba(91, 124, 255, 0.14)',
    border: 'rgba(91, 124, 255, 0.35)',
    label: 'Recent',
  },
  aging: {
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.35)',
    label: 'Aging',
  },
  stale: {
    bg: 'rgba(239, 68, 68, 0.1)',
    border: 'rgba(239, 68, 68, 0.3)',
    label: 'Stale',
  },
}

function nodeTypeLabel(t: string): string {
  const map: Record<string, string> = {
    evidence: 'Evidence',
    control: 'Control',
    golden_answer: 'Golden answer',
    answer: 'Answer',
  }
  return map[t] ?? t
}

export default function ProofChainPage() {
  const searchParams = useSearchParams()
  const initialId = searchParams.get('answer_id')?.trim() ?? ''

  const [answerIdInput, setAnswerIdInput] = useState(initialId)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<ChainResponse | null>(null)

  const loadChain = useCallback(
    async (raw: string) => {
      const id = parseInt(raw, 10)
      if (Number.isNaN(id) || id < 1) {
        setError('Enter a valid answer ID (positive integer).')
        setData(null)
        return
      }
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const r = await fetch(`/api/proof-graph/chain/answer/${id}`, {
          credentials: 'include',
        })
        if (r.status === 404) {
          setError(
            'No proof chain for this answer. Run proof graph sync (API POST /api/proof-graph/sync) after linking answers to your golden library, or use Review after generation.',
          )
          return
        }
        if (!r.ok) {
          setError(`Could not load chain (${r.status}).`)
          return
        }
        const body = (await r.json()) as ChainResponse
        setData(body)
      } catch {
        setError('Network error loading proof chain.')
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (initialId) void loadChain(initialId)
  }, [initialId, loadChain])

  const steps = useMemo(() => data?.chain ?? [], [data])

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <Link href="/dashboard" className="text-sm text-[var(--tc-muted)] hover:text-[var(--tc-text)]">
          ← Dashboard
        </Link>
      </div>
      <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-1">Proof chain</h1>
      <p className="text-sm text-[var(--tc-muted)] mb-6 max-w-xl">
        Trace how a questionnaire answer connects to golden answers, controls, and evidence. Use this in reviews and deal rooms to verify the reasoning path behind an answer.
      </p>

      <Card className="mb-8 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <label htmlFor="proof-answer-id" className="mb-1.5 block text-xs font-medium text-[var(--tc-muted)]">
              Answer ID
            </label>
            <Input
              id="proof-answer-id"
              inputMode="numeric"
              placeholder="e.g. 42"
              value={answerIdInput}
              onChange={(e) => setAnswerIdInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void loadChain(answerIdInput)
              }}
            />
          </div>
          <Button type="button" onClick={() => void loadChain(answerIdInput)} disabled={loading}>
            {loading ? 'Loading…' : 'Load chain'}
          </Button>
        </div>
        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
      </Card>

      {loading && (
        <Card className="p-6">
          <Skeleton height={20} className="mb-4 w-2/3" />
          <Skeleton height={64} className="mb-3" />
          <Skeleton height={64} className="mb-3" />
          <Skeleton height={64} />
        </Card>
      )}

      {!loading && data && steps.length > 0 && (
        <div>
          <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">
            Chain for answer #{data.answer_id} ({steps.length} nodes) — source → answer
          </p>
          <ol className="relative grid gap-0 border-l-2 border-[var(--tc-border)] pl-6 ml-2">
            {steps.map((node, idx) => {
              const fs = FRESHNESS_STYLE[node.freshness] ?? FRESHNESS_STYLE.aging
              return (
                <li key={`${node.id}-${idx}`} className="relative pb-8 last:pb-0">
                  <span
                    className="absolute -left-[calc(0.5rem+5px)] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--tc-bg)]"
                    style={{ background: fs.border }}
                    aria-hidden
                  />
                  <div
                    className="rounded-xl border p-4 transition"
                    style={{ background: fs.bg, borderColor: fs.border }}
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="rounded-md border border-[var(--tc-border)] bg-white/5 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--tc-text)]">
                        {nodeTypeLabel(node.node_type)}
                      </span>
                      <span
                        className="rounded-md px-2 py-0.5 text-[11px] font-medium text-[var(--tc-text)]"
                        style={{ border: `1px solid ${fs.border}` }}
                      >
                        {fs.label}
                      </span>
                      {node.ref_table && node.ref_id != null && (
                        <span className="text-[11px] text-[var(--tc-muted)]">
                          {node.ref_table} #{node.ref_id}
                        </span>
                      )}
                    </div>
                    {node.label && (
                      <p className="text-sm leading-snug text-[var(--tc-text)] line-clamp-4" title={node.label}>
                        {node.label}
                      </p>
                    )}
                    {node.meta_json && (
                      <pre className="mt-2 max-h-24 overflow-auto rounded-lg border border-[var(--tc-border)] bg-black/20 p-2 text-[10px] text-[var(--tc-muted)]">
                        {node.meta_json}
                      </pre>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      )}

      {!loading && data && steps.length === 0 && (
        <p className="text-sm text-[var(--tc-muted)]">Chain is empty for this answer.</p>
      )}
    </div>
  )
}
