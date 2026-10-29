'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/ui'
import { ListSkeleton } from '@/components/ui/Skeleton'
import { useAuth } from '@/contexts/AuthContext'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { mutationFailureNotice, presentHttpFailure } from '@/lib/api-error'
import { actionVerb } from '@/lib/action-copy'
import {
  caseStudyQuoteFields,
  shouldResetCaseStudyFields,
} from '@/lib/render-state'
import {
  parseCaseStudyError,
  parseCaseStudyResponse,
  type CaseStudyView,
} from '@/lib/caseStudyConsumer'

const emptyForm = {
  title: '',
  synthetic: false,
  company_name: '',
  quote: '',
  results: '',
  metric_key: '',
  metric_value: '',
}

export default function CaseStudiesPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const canReview = permissions.can_review
  const [studies, setStudies] = useState<CaseStudyView[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const [createPending, setCreatePending] = useState(false)

  const applyList = (payload: unknown) => {
    const rec =
      payload && typeof payload === 'object'
        ? (payload as { case_studies?: unknown })
        : {}
    const rows = Array.isArray(rec.case_studies) ? rec.case_studies : []
    setStudies(rows.map((row) => parseCaseStudyResponse(row)))
  }

  const queryStudies = useCallback(() => {
    fetch('/api/case-studies', { credentials: 'include' })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}))
        if (!response.ok) {
          setLoadFailure(presentHttpFailure({ status: response.status }))
          setError(null)
          setStudies([])
          return
        }
        applyList(body)
        setError(null)
        setLoadFailure(null)
      })
      .catch(() => {
        setStudies([])
        setError(null)
        setLoadFailure(presentHttpFailure({ offline: true }))
      })
      .finally(() => setLoading(false))
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    queryStudies()
  }, [queryStudies])

  useEffect(() => {
    queryStudies()
  }, [queryStudies])

  const selected = studies.find((item) => item.id === selectedId) ?? null

  const replaceSelected = (body: unknown) => {
    const view = parseCaseStudyResponse(body)
    setStudies((current) => {
      const rest = current.filter((item) => item.id !== view.id)
      return [view, ...rest]
    })
    setSelectedId(view.id)
    return view
  }

  const postJson = async (url: string, payload: unknown) => {
    setSaving(true)
    setError(null)
    try {
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        const mapped = mutationFailureNotice(
          response.status,
          body,
          'The change was not saved. Try again.'
        )
        setError(
          mapped.title === 'Could not complete that'
            ? parseCaseStudyError(body).message
            : mapped.message
        )
        return null
      }
      return replaceSelected(body)
    } catch {
      setError('The request failed.')
      return null
    } finally {
      setSaving(false)
    }
  }

  const createDraft = async () => {
    const metrics =
      form.metric_key.trim() && form.metric_value.trim()
        ? { [form.metric_key.trim()]: form.metric_value.trim() }
        : undefined
    setSaving(true)
    setCreatePending(true)
    setError(null)
    try {
      const response = await fetch('/api/case-studies', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title.trim(),
          synthetic: form.synthetic,
          company_name: form.company_name.trim() || null,
          quote: form.quote.trim() || null,
          results: form.results.trim() || null,
          metrics,
        }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        const mapped = mutationFailureNotice(
          response.status,
          body,
          'The draft could not be saved.'
        )
        setError(
          mapped.title === 'Could not complete that'
            ? parseCaseStudyError(body).message
            : mapped.message
        )
        return
      }
      replaceSelected(body)
      setForm(emptyForm)
    } catch {
      setError('The draft could not be saved.')
    } finally {
      setSaving(false)
      setCreatePending(false)
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-[var(--tc-text)]">
          Case studies
        </h1>
        <p className="text-sm text-[var(--tc-muted)]">
          A draft is not a customer claim. Publication checks organization
          consent and permission for every quoted result. Synthetic examples
          stay labeled synthetic.
        </p>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-200"
        >
          {error}
        </p>
      )}

      {canAdmin && (
        <Card>
          <form
            className="grid gap-3"
            onSubmit={(event) => {
              event.preventDefault()
              void createDraft()
            }}
          >
            <h2 className="text-sm font-semibold text-[var(--tc-text)]">
              New draft
            </h2>
            <label
              className="grid gap-1 text-sm text-[var(--tc-muted)]"
              htmlFor="case-title"
            >
              Title
              <input
                id="case-title"
                required
                value={form.title}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
                className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
              />
            </label>
            <label
              className="flex items-center gap-2 text-sm text-[var(--tc-text)]"
              htmlFor="case-synthetic"
            >
              <input
                id="case-synthetic"
                type="checkbox"
                checked={form.synthetic}
                onChange={(event) =>
                  setForm({ ...form, synthetic: event.target.checked })
                }
              />
              Synthetic example. This cannot become a customer claim.
            </label>
            <label
              className="grid gap-1 text-sm text-[var(--tc-muted)]"
              htmlFor="case-org"
            >
              Quoted organization
              <input
                id="case-org"
                value={form.company_name}
                onChange={(event) =>
                  setForm({ ...form, company_name: event.target.value })
                }
                className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
              />
            </label>
            <label
              className="grid gap-1 text-sm text-[var(--tc-muted)]"
              htmlFor="case-quote"
            >
              Quote
              <textarea
                id="case-quote"
                value={form.quote}
                onChange={(event) =>
                  setForm({ ...form, quote: event.target.value })
                }
                className="min-h-20 rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
              />
            </label>
            <label
              className="grid gap-1 text-sm text-[var(--tc-muted)]"
              htmlFor="case-results"
            >
              Results narrative
              <textarea
                id="case-results"
                value={form.results}
                onChange={(event) =>
                  setForm({ ...form, results: event.target.value })
                }
                className="min-h-20 rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label
                className="grid gap-1 text-sm text-[var(--tc-muted)]"
                htmlFor="case-metric-key"
              >
                Result field name
                <input
                  id="case-metric-key"
                  value={form.metric_key}
                  onChange={(event) =>
                    setForm({ ...form, metric_key: event.target.value })
                  }
                  className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
                />
              </label>
              <label
                className="grid gap-1 text-sm text-[var(--tc-muted)]"
                htmlFor="case-metric-value"
              >
                Result field value
                <input
                  id="case-metric-value"
                  value={form.metric_value}
                  onChange={(event) =>
                    setForm({ ...form, metric_value: event.target.value })
                  }
                  className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
                />
              </label>
            </div>
            <div>
              <Button
                type="submit"
                disabled={saving || !form.title.trim()}
                loading={createPending}
              >
                {createPending
                  ? actionVerb('save', 'pending')
                  : `${actionVerb('save', 'idle')} draft`}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loadFailure ? (
        <ErrorState failure={loadFailure} onRetry={() => void load()} />
      ) : loading ? (
        <LoadingState label="Loading case studies" onRetry={() => void load()}>
          <ListSkeleton />
        </LoadingState>
      ) : studies.length === 0 ? (
        <EmptyState
          title="No case studies"
          description="Nothing on this page is a customer claim until a publication is consented."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <ul className="grid gap-3">
            {studies.map((study) => (
              <li key={study.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(study.id)}
                  className={`w-full rounded-2xl border px-4 py-3 text-left ${
                    selectedId === study.id
                      ? 'border-[rgba(91,124,255,0.45)] bg-white/10'
                      : 'border-[var(--tc-border)] bg-white/5'
                  }`}
                >
                  <span className="block text-sm font-medium text-[var(--tc-text)]">
                    {study.title}
                  </span>
                  <span className="mt-1 block text-xs uppercase tracking-wide text-[var(--tc-muted)]">
                    Workflow status: {study.status}
                  </span>
                  <span className="mt-1 block text-sm text-[var(--tc-text)]">
                    {study.display_label}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <Card>
              <StudyDetail
                study={selected}
                canAdmin={canAdmin}
                canReview={canReview}
                saving={saving}
                onAction={postJson}
              />
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

function StudyDetail({
  study,
  canAdmin,
  canReview,
  saving,
  onAction,
}: {
  study: CaseStudyView
  canAdmin: boolean
  canReview: boolean
  saving: boolean
  onAction: (url: string, payload: unknown) => Promise<CaseStudyView | null>
}) {
  const [organizationName, setOrganizationName] = useState(
    study.company_name ?? ''
  )
  const [consentReference, setConsentReference] = useState('')
  const [resultKey, setResultKey] = useState(study.quoted_results[0] ?? '')
  const [consentId, setConsentId] = useState('')
  const [approvePending, setApprovePending] = useState(false)
  const quoteSource = {
    id: study.id,
    companyName: study.company_name,
    quotedResults: study.quoted_results,
  }
  const [seenQuote, setSeenQuote] = useState(quoteSource)
  if (shouldResetCaseStudyFields(seenQuote, quoteSource)) {
    const fields = caseStudyQuoteFields(study)
    setSeenQuote(quoteSource)
    setOrganizationName(fields.organizationName)
    setResultKey(fields.resultKey)
  }

  const revision = { expected_revision: study.revision }

  return (
    <div className="grid gap-3">
      <h2 className="text-base font-semibold text-[var(--tc-text)]">
        {study.title}
      </h2>
      <p className="text-sm text-[var(--tc-text)]">{study.display_label}</p>
      <p className="text-xs uppercase tracking-wide text-[var(--tc-muted)]">
        Workflow status: {study.status}
      </p>
      {study.blockers.length > 0 && (
        <ul className="grid gap-1 text-sm text-[var(--tc-muted)]">
          {study.blockers.map((blocker, index) => (
            <li key={`${blocker.code}-${blocker.field}-${index}`}>
              Blocked: {blocker.code}
              {blocker.field ? ` (${blocker.field})` : ''}
            </li>
          ))}
        </ul>
      )}
      {canAdmin && study.status === 'draft' && (
        <Button
          type="button"
          disabled={saving}
          onClick={() =>
            void onAction(
              `/api/case-studies/${study.id}/submit-review`,
              revision
            )
          }
        >
          Submit for review
        </Button>
      )}
      {canReview &&
        study.status === 'in_review' &&
        study.review_status !== 'approved' && (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={saving}
              loading={approvePending}
              onClick={() => {
                setApprovePending(true)
                void onAction(`/api/case-studies/${study.id}/review`, {
                  ...revision,
                  decision: 'approve',
                }).finally(() => setApprovePending(false))
              }}
            >
              {approvePending
                ? actionVerb('approve', 'pending')
                : `${actionVerb('approve', 'idle')} review`}
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() =>
                void onAction(`/api/case-studies/${study.id}/review`, {
                  ...revision,
                  decision: 'request_changes',
                })
              }
            >
              Request changes
            </Button>
          </div>
        )}
      {canAdmin &&
        study.review_status === 'approved' &&
        study.status !== 'published' && (
          <Button
            type="button"
            disabled={saving}
            onClick={() =>
              void onAction(`/api/case-studies/${study.id}/publish`, revision)
            }
          >
            Publish
          </Button>
        )}
      {canAdmin && study.status === 'published' && (
        <Button
          type="button"
          variant="secondary"
          disabled={saving}
          onClick={() =>
            void onAction(`/api/case-studies/${study.id}/withdraw`, revision)
          }
        >
          Withdraw publication
        </Button>
      )}
      {canAdmin && (
        <form
          className="grid gap-2 border-t border-[var(--tc-border)] pt-3"
          onSubmit={(event) => {
            event.preventDefault()
            void onAction(`/api/case-studies/${study.id}/consents`, {
              organization_name: organizationName,
              consent_reference: consentReference || null,
              expected_revision: study.revision,
            })
          }}
        >
          <h3 className="text-sm font-semibold text-[var(--tc-text)]">
            Organization consent
          </h3>
          <label
            className="grid gap-1 text-sm text-[var(--tc-muted)]"
            htmlFor="consent-org"
          >
            Quoted organization
            <input
              id="consent-org"
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
            />
          </label>
          <label
            className="grid gap-1 text-sm text-[var(--tc-muted)]"
            htmlFor="consent-ref"
          >
            Consent reference
            <input
              id="consent-ref"
              value={consentReference}
              onChange={(event) => setConsentReference(event.target.value)}
              className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
            />
          </label>
          <Button type="submit" disabled={saving || !organizationName.trim()}>
            Record consent
          </Button>
        </form>
      )}
      {canAdmin && (
        <form
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void onAction(`/api/case-studies/${study.id}/result-permissions`, {
              consent_id: Number(consentId),
              result_key: resultKey,
              expected_revision: study.revision,
            })
          }}
        >
          <h3 className="text-sm font-semibold text-[var(--tc-text)]">
            Result permission
          </h3>
          <label
            className="grid gap-1 text-sm text-[var(--tc-muted)]"
            htmlFor="permission-consent"
          >
            Consent id
            <input
              id="permission-consent"
              inputMode="numeric"
              value={consentId}
              onChange={(event) => setConsentId(event.target.value)}
              className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
            />
          </label>
          <label
            className="grid gap-1 text-sm text-[var(--tc-muted)]"
            htmlFor="permission-result"
          >
            Quoted result
            <input
              id="permission-result"
              value={resultKey}
              onChange={(event) => setResultKey(event.target.value)}
              className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-[var(--tc-text)]"
            />
          </label>
          <Button
            type="submit"
            disabled={saving || !consentId.trim() || !resultKey.trim()}
          >
            Record permission
          </Button>
        </form>
      )}
    </div>
  )
}
