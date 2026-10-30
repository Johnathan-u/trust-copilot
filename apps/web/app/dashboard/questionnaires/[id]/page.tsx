'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Button, Card, Skeleton } from '@/components/ui'
import { ErrorState, LoadingState } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  mutationFailureNotice,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import { actionVerb } from '@/lib/action-copy'
import { failureOf, isAbortError, readSectionJson } from '@/lib/section-load'

interface ParsedQuestion {
  id: number
  text: string
  section: string | null
  answer_type: string | null
}

interface DocRow {
  id: number
  filename: string
}

interface QnrDetail {
  id: number
  document_id: number | null
  filename: string
  status: string
  parse_metadata: string | null
  questions: ParsedQuestion[]
  answer_evidence_document_ids?: number[]
  answer_evidence_documents?: { id: number; filename: string }[]
}

interface AnswerStats {
  questionnaire_id: number
  total_questions: number
  total_answers: number
  answered: number
  not_answered: number
  status_breakdown: Record<string, number>
  gating_breakdown: Record<string, number>
  insufficient_breakdown: Record<string, number>
  category_gaps: Record<string, number>
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  insufficient_evidence: 'Insufficient evidence',
  sufficient: 'Sufficient',
  reviewed: 'Reviewed',
  approved: 'Approved',
  rejected: 'Rejected',
}

const GATING_LABELS: Record<string, string> = {
  no_evidence: 'No evidence available',
  retrieval_noise_floor: 'Evidence too generic',
  below_confidence_threshold: 'Low confidence',
  empty_retrieval: 'No matching documents',
  question_too_short: 'Question too short',
  duplicate_question: 'Duplicate question',
  unknown: 'Unknown reason',
}

export default function QuestionnaireDetailPage() {
  const params = useParams()
  const id = params.id as string
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canEdit = permissions.can_edit
  const [qnr, setQnr] = useState<QnrDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [workspaceDocs, setWorkspaceDocs] = useState<DocRow[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [savingEvidence, setSavingEvidence] = useState(false)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [evidenceSaved, setEvidenceSaved] = useState(false)
  const [answerStats, setAnswerStats] = useState<AnswerStats | null>(null)

  const loadQnr = useCallback(() => {
    if (workspaceId == null) return
    fetch(`/api/questionnaires/${id}?workspace_id=${workspaceId}`, {
      credentials: 'include',
    })
      .then((r) => readSectionJson(r))
      .then((data) => {
        const detail = data as QnrDetail
        setQnr(detail)
        setLoadFailure(null)
        const ids = detail.answer_evidence_document_ids ?? []
        setSelectedIds(new Set(ids))
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        setQnr(null)
        setLoadFailure(failureOf(error))
      })
      .finally(() => setLoading(false))
  }, [id, workspaceId])

  useEffect(() => {
    loadQnr()
  }, [loadQnr])

  const qnrId = qnr?.id
  useEffect(() => {
    if (workspaceId == null || qnrId == null) return
    fetch(`/api/ai-governance/questionnaire-answer-stats/${qnrId}`, {
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d && !d.error) setAnswerStats(d as AnswerStats)
      })
      .catch(() => {})
  }, [workspaceId, qnrId])

  useEffect(() => {
    if (workspaceId == null) return
    fetch(`/api/documents?workspace_id=${workspaceId}`, {
      credentials: 'include',
    })
      .then((r) => readSectionJson(r))
      .then((rows) => {
        if (Array.isArray(rows)) setWorkspaceDocs(rows as DocRow[])
        else if (
          rows &&
          typeof rows === 'object' &&
          Array.isArray((rows as { documents?: unknown }).documents)
        ) {
          setWorkspaceDocs((rows as { documents: DocRow[] }).documents)
        } else if (
          rows &&
          typeof rows === 'object' &&
          Array.isArray((rows as { items?: unknown }).items)
        ) {
          setWorkspaceDocs((rows as { items: DocRow[] }).items)
        } else {
          throw new Error('malformed')
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        setWorkspaceDocs([])
        setLoadFailure((current) => current ?? failureOf(error))
      })
  }, [workspaceId])

  const selectableDocs = useMemo(() => {
    const qDoc = qnr?.document_id ?? null
    return workspaceDocs.filter((d) => qDoc == null || d.id !== qDoc)
  }, [workspaceDocs, qnr?.document_id])

  const toggleDoc = (docId: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(docId)) next.delete(docId)
      else next.add(docId)
      return next
    })
    setEvidenceSaved(false)
  }

  const saveAnswerEvidence = async () => {
    if (workspaceId == null || !canEdit) return
    setSavingEvidence(true)
    setEvidenceSaved(false)
    setEvidenceError(null)
    try {
      const r = await fetch(
        `/api/questionnaires/${id}/answer-evidence?workspace_id=${workspaceId}`,
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ document_ids: Array.from(selectedIds) }),
        }
      )
      if (!r.ok) {
        const err = await r.json().catch(() => null)
        setEvidenceSaved(false)
        setEvidenceError(
          mutationFailureNotice(
            r.status,
            err,
            'The change was not saved. Try again.'
          ).message
        )
        return
      }
      const data = await r.json()
      setQnr((q) =>
        q
          ? {
              ...q,
              answer_evidence_document_ids: data.answer_evidence_document_ids,
              answer_evidence_documents: data.answer_evidence_documents,
            }
          : q
      )
      setSelectedIds(new Set(data.answer_evidence_document_ids ?? []))
      setEvidenceSaved(true)
    } catch (e) {
      setEvidenceError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSavingEvidence(false)
    }
  }

  const selectedList = useMemo(() => {
    const fromApi = qnr?.answer_evidence_documents ?? []
    const map = new Map(fromApi.map((d) => [d.id, d.filename]))
    for (const d of workspaceDocs) {
      if (!map.has(d.id)) map.set(d.id, d.filename)
    }
    return Array.from(selectedIds)
      .sort((a, b) => a - b)
      .map((docId) => ({
        id: docId,
        filename: map.get(docId) ?? `Document #${docId}`,
      }))
  }, [selectedIds, qnr?.answer_evidence_documents, workspaceDocs])

  const evidenceSummary =
    selectedIds.size === 0
      ? 'Using workspace documents by default for draft answers.'
      : selectedIds.size === 1
        ? 'Using 1 selected document for draft answers.'
        : `Using ${selectedIds.size} selected documents for draft answers.`

  if (loading)
    return (
      <LoadingState label="Loading questionnaire" onRetry={() => loadQnr()}>
        <div className="p-7 space-y-6">
          <Skeleton width={200} height={16} />
          <Skeleton width="80%" height={32} />
          <Card className="space-y-3">
            <Skeleton width="40%" height={20} />
            <Skeleton width="30%" height={20} />
          </Card>
          <Card padding="none">
            <div className="p-4 border-b border-[var(--tc-border)]">
              <Skeleton width={180} height={18} />
            </div>
            <div className="p-4 space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex gap-4">
                  <Skeleton width={32} height={18} />
                  <Skeleton width="70%" height={18} />
                  <Skeleton width={100} height={18} />
                  <Skeleton width={80} height={18} />
                </div>
              ))}
            </div>
          </Card>
        </div>
      </LoadingState>
    )
  if (!qnr)
    return loadFailure ? (
      <ErrorState failure={loadFailure} onRetry={() => loadQnr()} />
    ) : (
      <p className="text-tc-label text-tc-muted">
        We could not find that.{' '}
        <Link
          href="/dashboard/questionnaires"
          className="text-tc-text underline"
        >
          Back
        </Link>
      </p>
    )

  let meta: { count?: number } | null = null
  try {
    meta = qnr.parse_metadata ? JSON.parse(qnr.parse_metadata) : null
  } catch {
    /* ignore */
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          href="/dashboard/questionnaires"
          className="text-sm text-[var(--tc-muted)] hover:text-[var(--tc-text)]"
        >
          ← Questionnaires
        </Link>
      </div>
      <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-6">
        {qnr.filename}
      </h1>
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-4 text-sm text-[var(--tc-text)]">
          <span>
            <strong>Status:</strong> {qnr.status}
          </span>
          {meta?.count != null && (
            <span>
              <strong>Questions:</strong> {meta.count}
            </span>
          )}
          <Link
            href={`/dashboard/review/${id}`}
            className="tc-btn-primary inline-flex min-h-tc-6 items-center rounded-tc-sm px-tc-3 py-tc-1 text-tc-label font-medium"
          >
            Review answers
          </Link>
        </div>

        <div className="mt-6 pt-6 border-t border-[var(--tc-border)]">
          <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">
            Answer evidence
          </h2>
          <p className="text-xs text-[var(--tc-muted)] mb-3 max-w-2xl">
            Select which documents the AI may cite when generating answers for
            this questionnaire. Narrowing this list improves answer quality and
            auditability.
          </p>
          <p className="text-xs text-[var(--tc-soft)] mb-3">
            {evidenceSummary}
          </p>

          {selectableDocs.length === 0 ? (
            <p className="text-sm text-[var(--tc-muted)]">
              No other documents in this workspace yet. Upload evidence under
              Documents, then return here.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2 mb-3">
              {selectableDocs.map((d) => (
                <label
                  key={d.id}
                  className={`inline-flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-xs transition ${
                    selectedIds.has(d.id)
                      ? 'border-[rgba(91,124,255,0.45)] bg-[rgba(91,124,255,0.12)] text-[var(--tc-text)]'
                      : 'border-[var(--tc-border)] bg-[var(--tc-panel-2)] text-[var(--tc-muted)] hover:border-[var(--tc-border-strong)]'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="rounded border-[var(--tc-border)]"
                    checked={selectedIds.has(d.id)}
                    disabled={!canEdit}
                    onChange={() => toggleDoc(d.id)}
                  />
                  <span className="max-w-[220px] truncate" title={d.filename}>
                    {d.filename}
                  </span>
                </label>
              ))}
            </div>
          )}

          {selectedList.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-[var(--tc-muted)] mb-1.5">
                Selected
              </p>
              <ul className="flex flex-wrap gap-2">
                {selectedList.map((d) => (
                  <li
                    key={d.id}
                    className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-2.5 py-1 text-xs text-[var(--tc-text)] max-w-[280px] truncate"
                    title={d.filename}
                  >
                    {d.filename}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {canEdit ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={saveAnswerEvidence}
                disabled={savingEvidence}
              >
                {savingEvidence
                  ? actionVerb('save', 'pending')
                  : `${actionVerb('save', 'idle')} answer evidence`}
              </Button>
              {evidenceSaved && !savingEvidence && (
                <span className="text-xs text-[var(--tc-success)]">
                  {actionVerb('save', 'success')}
                </span>
              )}
              {evidenceError && (
                <span className="text-xs text-red-400">{evidenceError}</span>
              )}
            </div>
          ) : (
            <p className="text-xs text-[var(--tc-muted)]">
              You can view this list; only editors can change which documents
              are used.
            </p>
          )}
        </div>
      </Card>
      {answerStats && (
        <Card className="mb-6">
          <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">
            Answer summary
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            <div className="rounded-lg border border-[var(--tc-border)] p-3 text-center">
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">
                Questions
              </div>
              <div className="text-xl font-bold text-[var(--tc-text)]">
                {answerStats.total_questions}
              </div>
            </div>
            <div className="rounded-lg border border-[var(--tc-border)] p-3 text-center">
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">
                Answered
              </div>
              <div className="text-xl font-bold text-emerald-400">
                {answerStats.answered}
              </div>
            </div>
            <div className="rounded-lg border border-[var(--tc-border)] p-3 text-center">
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">
                Not answered
              </div>
              <div className="text-xl font-bold text-amber-400">
                {answerStats.not_answered}
              </div>
            </div>
            <div className="rounded-lg border border-[var(--tc-border)] p-3 text-center">
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">
                Total drafts
              </div>
              <div className="text-xl font-bold text-[var(--tc-text)]">
                {answerStats.total_answers}
              </div>
            </div>
          </div>
          {Object.keys(answerStats.status_breakdown).length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-[var(--tc-muted)] mb-1">
                Status
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(answerStats.status_breakdown).map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded-full border border-[var(--tc-border)] px-2.5 py-0.5 text-xs text-[var(--tc-text)]"
                  >
                    {STATUS_LABELS[k] ?? k}: <strong>{v}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}
          {Object.keys(answerStats.gating_breakdown).length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-medium text-[var(--tc-muted)] mb-1">
                Why some questions were skipped
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(answerStats.gating_breakdown).map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-xs text-amber-400"
                  >
                    {GATING_LABELS[k] ?? k}: <strong>{v}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 border-b border-[var(--tc-border)]">
          <h2 className="font-semibold text-[var(--tc-text)]">
            Parsed questions
          </h2>
        </div>
        {qnr.questions?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr
                  className="border-b border-[var(--tc-border-strong)]"
                  style={{ background: 'var(--tc-panel-2)' }}
                >
                  <th className="text-left p-3 font-medium text-[var(--tc-muted)]">
                    #
                  </th>
                  <th className="text-left p-3 font-medium text-[var(--tc-muted)]">
                    Question
                  </th>
                  <th className="text-left p-3 font-medium text-[var(--tc-muted)]">
                    Section
                  </th>
                  <th className="text-left p-3 font-medium text-[var(--tc-muted)]">
                    Type
                  </th>
                </tr>
              </thead>
              <tbody>
                {qnr.questions.map((q, i) => (
                  <tr key={q.id} className="border-t border-[var(--tc-border)]">
                    <td className="p-3 text-[var(--tc-muted)]">{i + 1}</td>
                    <td className="p-3 text-[var(--tc-text)]">{q.text}</td>
                    <td className="p-3 text-[var(--tc-muted)]">
                      {q.section || '-'}
                    </td>
                    <td className="p-3 text-[var(--tc-muted)]">
                      {q.answer_type || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="p-6 text-[var(--tc-muted)]">
            No questions parsed yet. Upload an XLSX and run the worker to parse.
          </p>
        )}
      </Card>
    </div>
  )
}
