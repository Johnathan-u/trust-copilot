'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'
import { vendorRequestWithoutToken } from '@/lib/render-state'

type QuestionnaireInfo = {
  name: string
  question_count: number
}

type RequestData = {
  status: string
  message: string | null
  questionnaire: QuestionnaireInfo | null
}

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pending',
  in_progress: 'In Progress',
  completed: 'Completed',
}

const GENERIC_LINK_ERROR = 'This link is invalid or has expired.'

export default function VendorResponsePage() {
  return (
    <Suspense
      fallback={
        <Shell>
          <div className="flex items-center justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#5b7cff] border-t-transparent" />
          </div>
        </Shell>
      }
    >
      <VendorResponseContent />
    </Suspense>
  )
}

function VendorResponseContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token')

  const [data, setData] = useState<RequestData | null>(null)
  const initialToken = vendorRequestWithoutToken(token)
  const [loading, setLoading] = useState(initialToken.loading)
  const [error, setError] = useState<string | null>(initialToken.error)
  const tokenKey = useKeyedGeneration(token ?? '', { runOnMount: false })
  if (tokenKey.changed) {
    const next = vendorRequestWithoutToken(token)
    setLoading(next.loading)
    setError(next.error)
  }

  useEffect(() => {
    if (!token) return
    fetch(`/api/vendor-response?token=${encodeURIComponent(token)}`)
      .then((r) => {
        if (r.status === 404) throw new Error('invalid')
        if (!r.ok) throw new Error('server')
        return r.json()
      })
      .then((d) => setData(d as RequestData))
      .catch((e) => {
        if (e.message === 'invalid') {
          setError(GENERIC_LINK_ERROR)
        } else {
          setError('Something went wrong. Please try again later.')
        }
      })
      .finally(() => setLoading(false))
  }, [token])

  if (loading) {
    return (
      <Shell>
        <div className="flex items-center justify-center py-20">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#5b7cff] border-t-transparent" />
        </div>
      </Shell>
    )
  }

  if (error) {
    return (
      <Shell>
        <div className="text-center py-16 px-4">
          <div className="text-4xl mb-4">🔗</div>
          <h2 className="text-lg font-semibold text-[var(--tc-text)]">
            Link Not Found
          </h2>
          <p className="mt-2 text-sm text-[var(--tc-muted)] max-w-sm mx-auto">
            {error}
          </p>
          <p className="mt-6 text-xs text-[var(--tc-muted)]">
            If you believe this is an error, contact the person who sent you
            this link.
          </p>
        </div>
      </Shell>
    )
  }

  if (!data) return null

  const isCompleted = data.status === 'completed'
  const hasQuestionnaire = data.questionnaire !== null

  if (isCompleted) {
    return (
      <Shell>
        <div className="text-center py-16 px-4">
          <div className="text-4xl mb-4">✅</div>
          <h2 className="text-lg font-semibold text-[var(--tc-text)]">
            Request Completed
          </h2>
          <p className="mt-2 text-sm text-[var(--tc-muted)] max-w-sm mx-auto">
            This request has already been completed. No further action is
            needed.
          </p>
        </div>
      </Shell>
    )
  }

  if (!token) return null

  return (
    <Shell>
      <div className="space-y-6">
        {/* Header */}
        <div className="text-center">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">
            Vendor Request
          </h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">
            You&apos;ve been asked to complete a security questionnaire.
          </p>
        </div>

        {/* Request Summary */}
        <div className="rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] p-5 space-y-4">
          {/* Status */}
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">
              Status
            </span>
            <StatusBadge status={data.status} />
          </div>

          {/* Questionnaire */}
          {hasQuestionnaire && (
            <div className="pt-3 border-t border-[var(--tc-border)]">
              <span className="text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide block mb-1">
                Questionnaire
              </span>
              <div className="flex items-center gap-2">
                <span className="text-base">📋</span>
                <div>
                  <p className="text-sm font-medium text-[var(--tc-text)]">
                    {data.questionnaire!.name}
                  </p>
                  {data.questionnaire!.question_count > 0 && (
                    <p className="text-xs text-[var(--tc-muted)]">
                      {data.questionnaire!.question_count} question
                      {data.questionnaire!.question_count !== 1 ? 's' : ''}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Message */}
          {data.message && (
            <div className="pt-3 border-t border-[var(--tc-border)]">
              <span className="text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide block mb-1">
                Message
              </span>
              <p className="text-sm text-[var(--tc-text)] whitespace-pre-wrap">
                {data.message}
              </p>
            </div>
          )}
        </div>

        {hasQuestionnaire ? (
          <p className="text-sm text-[var(--tc-muted)]">
            Answering each question on this page is not available yet. Submit
            your final response below.
          </p>
        ) : (
          <div className="rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] p-5 text-center">
            <p className="text-sm text-[var(--tc-muted)]">
              No questionnaire is attached to this request. Contact the sender
              for more details.
            </p>
          </div>
        )}

        <FinalResponseForm
          token={token}
          onCompleted={() =>
            setData((current) =>
              current ? { ...current, status: 'completed' } : current
            )
          }
          onGrantRejected={() => setError(GENERIC_LINK_ERROR)}
        />

        {/* Footer */}
        <p className="text-center text-[10px] text-[var(--tc-muted)] pt-2">
          This is a secure link. Do not share it with others.
        </p>
      </div>
    </Shell>
  )
}

function FinalResponseForm({
  token,
  onCompleted,
  onGrantRejected,
}: {
  token: string
  onCompleted: () => void
  onGrantRejected: () => void
}) {
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const lock = useRef(false)

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (lock.current) return
    if (!text.trim()) {
      setError('Enter a final response.')
      return
    }
    lock.current = true
    setSubmitting(true)
    setError(null)
    try {
      const result = await fetch('/api/vendor-response/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, response: text }),
      })
      if (result.status === 404) {
        onGrantRejected()
        return
      }
      if (result.status === 409) {
        setError('A different final response was already submitted.')
        return
      }
      const body = (await result.json().catch(() => null)) as {
        status?: unknown
        submitted_at?: unknown
      } | null
      if (
        !result.ok ||
        !body ||
        body.status !== 'completed' ||
        typeof body.submitted_at !== 'string'
      ) {
        setError('The response was not saved. Try again.')
        return
      }
      onCompleted()
    } catch {
      setError('Something went wrong. Please try again later.')
    } finally {
      lock.current = false
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" aria-busy={submitting}>
      <div>
        <label
          htmlFor="final-response"
          className="block text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide mb-1"
        >
          Final response
        </label>
        <textarea
          id="final-response"
          name="response"
          required
          maxLength={20000}
          rows={5}
          value={text}
          disabled={submitting}
          onChange={(event) => setText(event.target.value)}
          className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] resize-none focus:border-[#5b7cff] focus:outline-none focus:ring-2 focus:ring-[#5b7cff]/40"
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-400">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-[#5b7cff] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#4a6ae8] active:bg-[#3b5bdb] focus:outline-none focus:ring-2 focus:ring-[#5b7cff]/40 disabled:opacity-60"
      >
        {submitting ? 'Submitting...' : 'Submit response'}
      </button>
    </form>
  )
}

/* ── Layout shell ─────────────────────────────────────────────────────── */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--tc-bg,#0c0e14)] flex items-start justify-center px-4 py-10 sm:py-16">
      <div className="w-full max-w-md">
        {/* Logo / brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-[#5b7cff] flex items-center justify-center text-white text-sm font-bold">
              TC
            </div>
            <span className="text-sm font-semibold text-[var(--tc-text,#e4e6ea)] tracking-tight">
              Trust Copilot
            </span>
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}

/* ── Status badge ─────────────────────────────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-amber-500/15 text-amber-400',
    in_progress: 'bg-blue-500/15 text-blue-400',
    completed: 'bg-emerald-500/15 text-emerald-400',
  }
  const label = STATUS_LABELS[status] ?? status
  const color = styles[status] ?? 'bg-slate-500/15 text-slate-400'
  return (
    <span
      className={`text-[11px] font-semibold uppercase px-2 py-0.5 rounded ${color}`}
    >
      {label}
    </span>
  )
}
