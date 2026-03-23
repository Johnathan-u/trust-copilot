'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Button, Modal, Skeleton, TableSkeleton, Toast, TagList } from '@/components/ui'
import type { TagData } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { useAISettings } from '@/contexts/AISettingsContext'
import {
  answerStatusLabel,
  formatGenerationElapsed,
  generationPhaseMessage,
  isInsufficientAnswerText,
} from '@/lib/ai-review-copy'

const AUTOSAVE_DELAY_MS = 1500

type Citation = { chunk_id?: number; snippet?: string; tags?: TagData[] }
type Question = {
  id: number
  text: string
  answer?: { id: number; text: string | null; status: string; citations?: string } | null
}
type Qnr = { id: number; filename: string; questions: Question[] }

export default function ReviewPage() {
  const params = useParams()
  const id = params.id as string
  const { workspace, permissions } = useAuth()
  const { model: aiModel, responseStyle } = useAISettings()
  const workspaceId = workspace?.id
  const canExport = permissions.can_export
  const [qnr, setQnr] = useState<Qnr | null>(null)
  const [genJobId, setGenJobId] = useState<number | null>(null)
  const [exportJobId, setExportJobId] = useState<number | null>(null)
  const [exportRecords, setExportRecords] = useState<{ id: number; filename: string; created_at: string }[]>([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [citationDrawer, setCitationDrawer] = useState<{ questionText: string; citations: Citation[] } | null>(null)
  const [citationTags, setCitationTags] = useState<Record<number, TagData[]>>({})
  const [exportReadyToast, setExportReadyToast] = useState<{ filename: string } | null>(null)
  const [genSuccessToast, setGenSuccessToast] = useState(false)
  const [errorToast, setErrorToast] = useState<string | null>(null)
  const [isGenerateRequestInFlight, setIsGenerateRequestInFlight] = useState(false)
  const [loadError, setLoadError] = useState<boolean>(false)
  const pendingSaves = useRef<Map<number, { text: string; answerId?: number; timer: ReturnType<typeof setTimeout> }>>(new Map())
  const genPollStartedAt = useRef<number | null>(null)
  const exportPollStartedAt = useRef<number | null>(null)
  const GEN_POLL_TIMEOUT_MS = 600000 // 10 min max — AI generation can be slow for many questions
  const EXPORT_POLL_TIMEOUT_MS = 300000 // 5 min max for export jobs
  const [genElapsedSeconds, setGenElapsedSeconds] = useState(0)
  /** Last known job.status from GET /api/jobs/{id} while generation is in progress (queued | running | …). */
  const [genJobBackendStatus, setGenJobBackendStatus] = useState<string | null>(null)
  const [apiReachable, setApiReachable] = useState<boolean | null>(null)

  // Fetch parent-document tags when citation drawer opens
  useEffect(() => {
    if (!citationDrawer) { setCitationTags({}); return }
    const chunkIds = citationDrawer.citations.map((c) => c.chunk_id).filter((id): id is number => id != null)
    if (chunkIds.length === 0) return
    fetch('/api/tags/by-chunks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunk_ids: chunkIds }),
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : {}))
      .then((data: Record<string, TagData[]>) => {
        const mapped: Record<number, TagData[]> = {}
        for (const [k, v] of Object.entries(data)) mapped[Number(k)] = v
        setCitationTags(mapped)
      })
      .catch(() => setCitationTags({}))
  }, [citationDrawer])

  // One-time check: can we reach the API? (Logs showed "Failed to fetch" when API unreachable.)
  useEffect(() => {
    if (workspaceId == null) return
    const t = setTimeout(() => {
      fetch('/api/workspaces/current', { credentials: 'include', cache: 'no-store' })
        .then(() => setApiReachable(true))
        .catch(() => setApiReachable(false))
    }, 500)
    return () => clearTimeout(t)
  }, [workspaceId])

  const refresh = useCallback(() => {
    if (!id || workspaceId == null) return
    setLoadError(false)
    const url = `/api/questionnaires/${id}?workspace_id=${workspaceId}&_t=${Date.now()}`
    fetch(url, { credentials: 'include', cache: 'no-store', headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        setQnr(data)
        setLoadError(false)
      })
      .catch(() => {
        setQnr(null)
        setLoadError(true)
      })
    fetch(`/api/exports/records?workspace_id=${workspaceId}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then(setExportRecords)
      .catch(() => setExportRecords([]))
  }, [id, workspaceId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const saveAnswer = useCallback(
    async (questionId: number, text: string, answerId?: number, status?: string) => {
      const base = `/api/answers`
      const payload: { text?: string; status?: string } = { text }
      if (status) payload.status = status
      if (answerId) {
        await fetch(`${base}/${answerId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          credentials: 'include',
        })
      } else {
        await fetch(base, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question_id: questionId, text, status: status || 'draft' }),
          credentials: 'include',
        })
      }
      refresh()
    },
    [refresh]
  )

  const scheduleSave = useCallback((questionId: number, text: string, answerId?: number) => {
    const prev = pendingSaves.current.get(questionId)
    if (prev?.timer) clearTimeout(prev.timer)
    const timer = setTimeout(() => {
      saveAnswer(questionId, text, answerId)
      pendingSaves.current.delete(questionId)
    }, AUTOSAVE_DELAY_MS)
    pendingSaves.current.set(questionId, { text, answerId, timer })
  }, [saveAnswer])

  const updateAnswerText = useCallback((questionId: number, text: string) => {
    setQnr((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        questions: prev.questions.map((qq) =>
          qq.id === questionId
            ? { ...qq, answer: qq.answer ? { ...qq.answer, text } : { id: 0, text, status: 'draft', citations: undefined } }
            : qq
        ),
      }
    })
  }, [])

  const handleBlur = useCallback(
    (q: Question) => {
      const v = (q.answer?.text ?? '').trim()
      const prev = pendingSaves.current.get(q.id)
      if (prev?.timer) clearTimeout(prev.timer)
      pendingSaves.current.delete(q.id)
      if (q.answer?.id || v) saveAnswer(q.id, v, q.answer?.id)
    },
    [saveAnswer]
  )

  const bulkUpdate = useCallback(async (status: string) => {
    if (selected.size === 0) return
    await fetch(`/api/answers/bulk`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question_ids: Array.from(selected), status }),
      credentials: 'include',
    })
    setSelected(new Set())
    refresh()
  }, [selected, refresh])

  const GENERATE_REQUEST_TIMEOUT_MS = 20000 // 20s for initial enqueue; worker does the rest

  const handleGenerate = () => {
    if (workspaceId == null) {
      setErrorToast('Workspace not loaded. Please refresh the page.')
      setTimeout(() => setErrorToast(null), 5000)
      return
    }
    if (isGenerateRequestInFlight || genJobId) return
    const qnrId = typeof id === 'string' ? parseInt(id, 10) : Number(id)
    if (Number.isNaN(qnrId)) {
      setErrorToast('Invalid questionnaire. Refresh and try again.')
      setTimeout(() => setErrorToast(null), 5000)
      return
    }
    setIsGenerateRequestInFlight(true)
    setErrorToast(null)
    // Defer fetch so "Generating..." paints immediately and the UI stays responsive
    const doRequest = async () => {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), GENERATE_REQUEST_TIMEOUT_MS)
      try {
        const body = { model: aiModel || undefined, response_style: responseStyle || undefined }
        const r = await fetch(`/api/exports/generate/${qnrId}?workspace_id=${workspaceId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(body),
          signal: controller.signal,
        })
        clearTimeout(timeoutId)
        const data = await r.json().catch(() => ({}))
        if (r.ok && data?.job_id) {
          genPollStartedAt.current = Date.now()
          setGenJobBackendStatus(null)
          setGenJobId(data.job_id)
        } else {
          const raw = (data?.detail as string) || (Array.isArray(data?.detail) ? data.detail.map((x: { msg?: string }) => x.msg).join(', ') : '')
          const msg = r.status === 404 && (raw?.toLowerCase().includes('not found') || !raw)
            ? 'Questionnaire not found. It may have been deleted or you may not have access.'
            : r.status === 503 && raw
              ? raw
              : raw || 'Generate failed'
          setErrorToast(msg)
          setTimeout(() => setErrorToast(null), 6000)
        }
      } catch (e) {
        clearTimeout(timeoutId)
        const isFailedFetch = e instanceof Error && e.message === 'Failed to fetch'
        const message = e instanceof Error && e.name === 'AbortError'
          ? 'Request timed out. Ensure the API is running and try again.'
          : isFailedFetch
            ? 'Cannot reach the API. Start the full stack (e.g. node scripts/dev-all.js) so the API runs on port 8000, then try again.'
            : 'Network error. Ensure the API is running on port 8000.'
        setErrorToast(message)
        setTimeout(() => setErrorToast(null), 8000)
      } finally {
        setIsGenerateRequestInFlight(false)
      }
    }
    queueMicrotask(doRequest)
  }

  const handleExport = async (format: 'xlsx' | 'docx' = 'xlsx') => {
    if (workspaceId == null) {
      setErrorToast('Workspace not loaded. Please refresh the page.')
      setTimeout(() => setErrorToast(null), 5000)
      return
    }
    try {
      const r = await fetch(`/api/exports/export/${id}?workspace_id=${workspaceId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ format }),
      })
      const data = await r.json().catch(() => ({}))
      if (r.ok && data?.job_id) {
        exportPollStartedAt.current = Date.now()
        setExportJobId(data.job_id)
      }
      else setErrorToast((data?.detail as string) || (Array.isArray(data?.detail) ? data.detail.map((x: { msg?: string }) => x.msg).join(', ') : 'Export failed'))
      if (!r.ok) setTimeout(() => setErrorToast(null), 6000)
    } catch (e) {
      setErrorToast('Network error. Try again.')
      setTimeout(() => setErrorToast(null), 5000)
    }
  }

  const handleDownload = async (recordId: number, filename: string) => {
    if (workspaceId == null) return
    try {
      const r = await fetch(`/api/exports/records/${recordId}/download?workspace_id=${workspaceId}`, { credentials: 'include' })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        setErrorToast((data?.detail as string) || 'Download failed')
        setTimeout(() => setErrorToast(null), 5000)
        return
      }
      const blob = await r.blob()
      const disposition = r.headers.get('Content-Disposition')
      const match = disposition?.match(/filename\*?=(?:UTF-8'')?([^;]+)/)
      let name = filename || 'export.xlsx'
      if (match) {
        try {
          name = decodeURIComponent(match[1].trim().replace(/^["']|["']$/g, ''))
        } catch {
          name = filename || 'export.xlsx'
        }
      }
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      setErrorToast('Download failed. Try again.')
      setTimeout(() => setErrorToast(null), 5000)
    }
  }

  const clearGenPollTimer = useCallback(() => {
    genPollStartedAt.current = null
  }, [])

  const clearExportPollTimer = useCallback(() => {
    exportPollStartedAt.current = null
  }, [])

  const pollJob = useCallback(
    (jobId: number, kind: 'gen' | 'export') => {
      if (workspaceId == null) return
      fetch(`/api/jobs/${jobId}?workspace_id=${workspaceId}`, { credentials: 'include', cache: 'no-store' })
        .then(async (r) => (r.ok ? { j: await r.json(), status: r.status } : { j: null, status: r.status }))
        .then(({ j, status }) => {
          if (!j) {
            setGenJobId((prev) => (prev === jobId ? null : prev))
            setExportJobId((prev) => (prev === jobId ? null : prev))
            if (kind === 'gen') {
              clearGenPollTimer()
              setGenJobBackendStatus(null)
            }
            if (kind === 'export') clearExportPollTimer()
            setErrorToast(status >= 500 ? 'Server error. Try again later.' : 'Could not check job status. Try refreshing.')
            setTimeout(() => setErrorToast(null), 6000)
            return
          }
          if (kind === 'gen' && j.status !== 'completed' && j.status !== 'failed') {
            setGenJobBackendStatus(typeof j.status === 'string' ? j.status : null)
          }
          if (j.status === 'completed') {
            setGenJobId((prev) => (prev === jobId ? null : prev))
            setExportJobId((prev) => (prev === jobId ? null : prev))
            if (kind === 'gen') {
              clearGenPollTimer()
              setGenJobBackendStatus(null)
              setGenSuccessToast(true)
              setTimeout(() => setGenSuccessToast(false), 5000)
            }
            if (kind === 'export') clearExportPollTimer()
            refresh()
            if (kind === 'export') {
              const base = qnr?.filename?.replace(/\.[^.]+$/, '') || 'export'
              setExportReadyToast({ filename: `${base}_answered.xlsx` })
              setTimeout(() => setExportReadyToast(null), 8000)
            }
          } else if (j.status === 'failed') {
            setGenJobId((prev) => (prev === jobId ? null : prev))
            setExportJobId((prev) => (prev === jobId ? null : prev))
            if (kind === 'gen') {
              clearGenPollTimer()
              setGenJobBackendStatus(null)
            }
            if (kind === 'export') clearExportPollTimer()
            const detail = j.error ? String(j.error).slice(0, 160) : ''
            const fallback =
              kind === 'gen' ? 'Answer generation did not finish. Check that the worker is running and try again.' : 'Export did not finish. Try again.'
            setErrorToast(detail ? `${kind === 'gen' ? 'Answer generation failed' : 'Export failed'}: ${detail}` : fallback)
            setTimeout(() => setErrorToast(null), 8000)
          }
        })
        .catch(() => {
          setGenJobId((prev) => (prev === jobId ? null : prev))
          setExportJobId((prev) => (prev === jobId ? null : prev))
          if (kind === 'gen') {
            clearGenPollTimer()
            setGenJobBackendStatus(null)
          }
          if (kind === 'export') clearExportPollTimer()
          setErrorToast('Could not check job status. Try refreshing.')
          setTimeout(() => setErrorToast(null), 6000)
        })
    },
    [workspaceId, refresh, qnr?.filename, clearGenPollTimer, clearExportPollTimer]
  )

  // Poll job status every 2s
  useEffect(() => {
    if (!genJobId && !exportJobId) return
    const t = setInterval(() => {
      if (genJobId) {
        const started = genPollStartedAt.current
        if (started != null && Date.now() - started > GEN_POLL_TIMEOUT_MS) {
          genPollStartedAt.current = null
          setGenJobId(null)
          setGenJobBackendStatus(null)
          setGenElapsedSeconds(0)
          setErrorToast(
            'Answer generation is taking too long. If you use Docker, ensure the worker container is running (`docker compose ps`), then refresh and try again.'
          )
          setTimeout(() => setErrorToast(null), 10000)
          return
        }
        pollJob(genJobId, 'gen')
      }
      if (exportJobId) {
        const expStart = exportPollStartedAt.current
        if (expStart != null && Date.now() - expStart > EXPORT_POLL_TIMEOUT_MS) {
          exportPollStartedAt.current = null
          setExportJobId(null)
          setErrorToast('Export is taking too long. Ensure the worker is running, then refresh and try again.')
          setTimeout(() => setErrorToast(null), 10000)
          return
        }
        pollJob(exportJobId, 'export')
      }
    }, 2000)
    return () => clearInterval(t)
  }, [genJobId, exportJobId, pollJob])

  // Elapsed-time ticker so user sees the page is alive (not frozen) during long runs
  useEffect(() => {
    if (!genJobId && !isGenerateRequestInFlight) {
      setGenElapsedSeconds(0)
      return
    }
    const start = genPollStartedAt.current ?? Date.now()
    const tick = () => setGenElapsedSeconds(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [genJobId, isGenerateRequestInFlight])

  if (!qnr) {
    return (
      <div className="min-w-0 p-7">
        <div className="space-y-6">
          <Skeleton width={300} height={28} />
          <TableSkeleton rows={8} cols={4} />
          {loadError && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              Failed to load questionnaire. <button type="button" onClick={() => refresh()} className="underline font-medium">Retry</button>
            </div>
          )}
        </div>
      </div>
    )
  }

  const questions = qnr.questions || []
  const filtered = questions.filter((q) => {
    if (search && !q.text.toLowerCase().includes(search.toLowerCase())) return false
    const st = q.answer?.status ?? 'pending'
    if (statusFilter && st !== statusFilter) return false
    return true
  })

  const toggleSelect = (questionId: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(questionId)) next.delete(questionId)
      else next.add(questionId)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) setSelected(new Set())
    else setSelected(new Set(filtered.map((q) => q.id)))
  }

  const statusChips = [
    { value: null, label: 'All' },
    { value: 'pending', label: 'Not reviewed' },
    { value: 'draft', label: 'Draft answer' },
    { value: 'insufficient_evidence', label: 'Needs more evidence' },
    { value: 'approved', label: 'Approved' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'flagged', label: 'Needs attention' },
  ]

  const isInsufficientRow = (q: Question) =>
    isInsufficientAnswerText(q.answer?.text ?? null, q.answer?.status)

  const totalCount = questions.length
  const draftReadyCount = questions.filter((q) => q.answer?.text && !isInsufficientRow(q)).length
  const insufficientCount = questions.filter((q) => isInsufficientRow(q)).length
  const approvedCount = questions.filter((q) => q.answer?.status === 'approved').length

  const isGenerating = !!(genJobId || isGenerateRequestInFlight)
  const generationBanner = isGenerateRequestInFlight
    ? {
        title: 'Starting request…',
        subtitle: 'Sending your questionnaire to the answer service.',
      }
    : genJobId
      ? generationPhaseMessage(genJobBackendStatus)
      : null

  return (
    <div className="min-w-0 p-7">
      {apiReachable === false && (
        <div className="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <strong>Cannot reach the app backend.</strong> Draft answers and exports need the API running. If you use Docker:{' '}
          <code className="rounded bg-black/20 px-1">docker compose up -d</code> from the project folder. If you develop locally:{' '}
          <code className="rounded bg-black/20 px-1">node scripts/dev-all.js</code>
        </div>
      )}
      {generationBanner && (
        <div
          className="mb-4 rounded-xl border border-[rgba(91,124,255,0.25)] px-4 py-3 text-sm"
          style={{ background: 'rgba(91,124,255,0.08)' }}
        >
          <p className="font-semibold text-[var(--tc-text)]">{generationBanner.title}</p>
          <p className="mt-1 text-[var(--tc-muted)]">
            {generationBanner.subtitle}
            {genElapsedSeconds > 0 && (
              <span className="text-[var(--tc-text)]"> · Elapsed {formatGenerationElapsed(genElapsedSeconds)}</span>
            )}
          </p>
        </div>
      )}
      <div className="grid min-w-[1120px] gap-6">
        {/* Hero */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-[1.35fr_0.75fr]">
          <div
            className="relative overflow-hidden rounded-3xl border border-[var(--tc-border)] p-6"
            style={{ background: 'var(--tc-panel)', boxShadow: 'var(--tc-shadow)', backdropFilter: 'blur(20px)' }}
          >
            <div
              className="inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs"
              style={{
                background: 'rgba(91,124,255,0.1)',
                borderColor: 'rgba(91,124,255,0.18)',
                color: 'var(--tc-soft)',
              }}
            >
              Answer review · Evidence-backed drafts
            </div>
            <h1 className="mt-4 text-3xl font-bold leading-tight tracking-tight text-[var(--tc-text)]">
              Review draft answers, check supporting evidence, then approve and export.
            </h1>
            <p className="mt-3 max-w-[740px] text-[15px] leading-relaxed text-[var(--tc-muted)]">
              Draft answers are generated from your indexed documents. Edit text anytime, open supporting evidence when
              you need detail, then use bulk actions for approval. Export when the questionnaire is ready to share.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {canExport && (
                <>
                  <Button onClick={handleGenerate} disabled={apiReachable === false || !!genJobId || isGenerateRequestInFlight}>
                    {isGenerateRequestInFlight
                      ? 'Starting…'
                      : isGenerating
                        ? `Generating… ${genElapsedSeconds > 0 ? formatGenerationElapsed(genElapsedSeconds) : ''}`.trim()
                        : 'Generate draft answers'}
                  </Button>
                  {isGenerating && (
                    <span className="text-xs text-[var(--tc-muted)]">
                      Large questionnaires can take several minutes. You can keep using this page while drafts are prepared.
                    </span>
                  )}
                  <Button variant="ghost" onClick={() => handleExport('xlsx')} disabled={!!exportJobId}>
                    {exportJobId ? 'Exporting…' : 'Export XLSX'}
                  </Button>
                  <Button variant="ghost" onClick={() => handleExport('docx')} disabled={!!exportJobId}>
                    Export DOCX
                  </Button>
                  <span className="text-xs text-[var(--tc-muted)]">
                    AI settings: {aiModel || 'gpt-4o-mini'} · style {responseStyle}
                  </span>
                </>
              )}
            </div>
            <p className="mt-3 max-w-[740px] text-xs leading-relaxed text-[var(--tc-muted)]">
              Rows marked “needs more evidence” stay in the table for review; XLSX/DOCX exports replace them with a clear
              placeholder so they are not shared as if they were finalized answers.
            </p>
          </div>
          <div className="flex flex-col justify-center gap-3">
            <div
              className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-4"
            >
              <div>
                <strong className="text-xl text-[var(--tc-text)]">{totalCount}</strong>
                <br />
                <span className="text-xs text-[var(--tc-muted)]">Questions in this file</span>
              </div>
              <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">In progress</span>
            </div>
            <div
              className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-4"
            >
              <div>
                <strong className="text-xl text-[var(--tc-text)]">{draftReadyCount} / {totalCount}</strong>
                <br />
                <span className="text-xs text-[var(--tc-muted)]">Draft answers (real drafts)</span>
              </div>
              <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">
                {totalCount ? Math.round((draftReadyCount / totalCount) * 100) : 0}% drafted
              </span>
            </div>
            <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-4">
              <div>
                <strong className="text-xl text-[var(--tc-text)]">{insufficientCount}</strong>
                <br />
                <span className="text-xs text-[var(--tc-muted)]">Need more evidence</span>
              </div>
              <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">
                {approvedCount} approved
              </span>
            </div>
          </div>
        </section>

        {/* Table + Right stack */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_360px]">
          <div
            className="overflow-hidden rounded-3xl border border-[var(--tc-border)]"
            style={{ background: 'var(--tc-panel)', boxShadow: 'var(--tc-shadow)', backdropFilter: 'blur(20px)' }}
          >
            <div
              className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-gradient-to-b from-white/5 to-transparent px-6 py-4"
            >
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-[var(--tc-text)]">
                  {qnr.filename}
                </h2>
                <p className="text-[13px] text-[var(--tc-muted)]">
                  Dashboard → Questionnaires → Review → {qnr.filename}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {isGenerating && (
                  <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-muted)]">
                    Generating… {genElapsedSeconds > 0 ? formatGenerationElapsed(genElapsedSeconds) : ''}
                  </span>
                )}
                {canExport && (
                  <>
                    <Button size="sm" onClick={handleGenerate} disabled={apiReachable === false || !!genJobId || isGenerateRequestInFlight}>
                      {isGenerateRequestInFlight
                        ? 'Starting…'
                        : isGenerating
                          ? `Generating… ${genElapsedSeconds > 0 ? formatGenerationElapsed(genElapsedSeconds) : ''}`.trim()
                          : 'Generate draft answers'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => handleExport('xlsx')} disabled={!!exportJobId}>
                      Export XLSX
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => handleExport('docx')} disabled={!!exportJobId}>
                      Export DOCX
                    </Button>
                  </>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-b border-white/10 bg-white/5 px-6 py-4">
              {statusChips.map((s) => (
                <button
                  key={s.label}
                  onClick={() => setStatusFilter(s.value)}
                  className={`rounded-xl border px-3 py-2 text-xs transition ${
                    statusFilter === s.value
                      ? 'border-[rgba(91,124,255,0.22)] bg-[rgba(91,124,255,0.14)] text-[var(--tc-text)]'
                      : 'border-[var(--tc-border)] bg-white/5 text-[var(--tc-muted)] hover:bg-white/10 hover:text-[var(--tc-text)]'
                  }`}
                >
                  {s.label}
                </button>
              ))}
              <input
                type="search"
                placeholder="Search questions…"
                className="ml-auto min-w-[200px] rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:border-[var(--tc-primary)] focus:outline-none"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {selected.size > 0 && (
              <div
                className="flex flex-wrap items-center gap-2 border-b border-[rgba(91,124,255,0.12)] bg-[rgba(91,124,255,0.08)] px-6 py-3"
              >
                <span className="text-sm text-[var(--tc-text)]">{selected.size} selected</span>
                <Button size="sm" variant="secondary" onClick={() => bulkUpdate('approved')}>
                  Approve selected
                </Button>
                <Button size="sm" variant="secondary" onClick={() => bulkUpdate('rejected')}>
                  Reject
                </Button>
                <Button size="sm" variant="secondary" onClick={() => bulkUpdate('flagged')}>
                  Flag
                </Button>
                <button
                  type="button"
                  className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2.5 py-1.5 text-xs text-[var(--tc-text)] hover:bg-white/10"
                  onClick={() => setSelected(new Set())}
                >
                  Clear selection
                </button>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 bg-white/5">
                    <th className="w-14 px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">
                      <input
                        type="checkbox"
                        checked={filtered.length > 0 && selected.size === filtered.length}
                        onChange={toggleSelectAll}
                        className="h-4 w-4 rounded border-[var(--tc-border-strong)] bg-white/5"
                      />
                    </th>
                    <th className="w-16 px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">#</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Question</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Answer</th>
                    <th className="w-[150px] px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Status</th>
                    <th className="w-[140px] px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">
                      Supporting evidence
                    </th>
                    <th className="w-28 px-6 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Autosave</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((q, i) => {
                    const status = q.answer?.status ?? 'pending'
                    const statusClass =
                      status === 'approved'
                        ? 'tc-status-approved'
                        : status === 'draft'
                          ? 'tc-status-draft'
                          : status === 'flagged'
                            ? 'tc-status-flagged'
                            : ''
                    let citations: Citation[] = []
                    try {
                      if (q.answer?.citations) citations = JSON.parse(q.answer.citations) as Citation[]
                    } catch { /* ignore */ }
                    return (
                      <tr key={q.id} className="border-b border-white/10 hover:bg-white/[0.02]">
                        <td className="px-6 py-4">
                          <input
                            type="checkbox"
                            checked={selected.has(q.id)}
                            onChange={() => toggleSelect(q.id)}
                            className="h-4 w-4 rounded border-[var(--tc-border-strong)] bg-white/5"
                          />
                        </td>
                        <td className="px-6 py-4 text-[var(--tc-muted)]">{String(i + 1).padStart(2, '0')}</td>
                        <td className="max-w-[360px] px-6 py-4 text-[var(--tc-text)] leading-snug">{q.text}</td>
                        <td className="px-6 py-4">
                          <div
                            className="min-w-[300px] rounded-2xl border border-white/10 bg-white/5 p-3.5 text-[#d7e1f6] leading-snug shadow-inner"
                          >
                            <textarea
                              data-question-id={q.id}
                              className="w-full min-h-[80px] resize-y rounded-lg border-0 bg-transparent p-0 text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:ring-0"
                              value={q.answer?.text ?? ''}
                              onBlur={() => handleBlur(q)}
                              onChange={(e) => {
                                const v = e.target.value
                                updateAnswerText(q.id, v)
                                scheduleSave(q.id, v.trim(), q.answer?.id)
                              }}
                              placeholder="Edit draft answer…"
                            />
                            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--tc-muted)]">
                              <span>{pendingSaves.current.has(q.id) ? 'Saving…' : 'Saved'}</span>
                              <span>·</span>
                              <span>
                                {citations.length > 0
                                  ? `${citations.length} supporting source${citations.length !== 1 ? 's' : ''}`
                                  : 'No supporting evidence linked yet'}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <select
                            className={`rounded-xl border px-2.5 py-2 text-xs text-[var(--tc-text)] ${statusClass}`}
                            style={{ borderColor: 'var(--tc-border)' }}
                            value={status}
                            onChange={(e) => saveAnswer(q.id, q.answer?.text ?? '', q.answer?.id, e.target.value)}
                          >
                            <option value="pending">{answerStatusLabel('pending')}</option>
                            <option value="draft">{answerStatusLabel('draft')}</option>
                            <option value="insufficient_evidence">{answerStatusLabel('insufficient_evidence')}</option>
                            <option value="approved">{answerStatusLabel('approved')}</option>
                            <option value="rejected">{answerStatusLabel('rejected')}</option>
                            <option value="flagged">{answerStatusLabel('flagged')}</option>
                          </select>
                        </td>
                        <td className="px-6 py-4">
                          {citations.length > 0 ? (
                            <button
                              type="button"
                              className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2.5 py-2 text-xs text-[var(--tc-text)] hover:bg-white/10"
                              onClick={() => setCitationDrawer({ questionText: q.text, citations })}
                            >
                              View {citations.length} snippet{citations.length !== 1 ? 's' : ''}
                            </button>
                          ) : (
                            <span className="text-xs text-[var(--tc-muted)]">—</span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-xs text-[var(--tc-muted)]">—</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {filtered.length === 0 && (
              <p className="py-8 text-center text-[var(--tc-muted)]">No questions match filters</p>
            )}
          </div>

          <div className="flex flex-col gap-4 lg:sticky lg:top-7">
            {citationDrawer ? (
              <div
                className="rounded-3xl border border-[var(--tc-border)] p-5"
                style={{ background: 'var(--tc-panel)', boxShadow: 'var(--tc-shadow)', backdropFilter: 'blur(20px)' }}
              >
                <h3 className="mb-2 text-lg font-semibold tracking-tight text-[var(--tc-text)]">Supporting evidence</h3>
                <p className="mb-4 text-[13px] leading-relaxed text-[var(--tc-muted)]">
                  Snippets from your documents that the draft answer was grounded on. Read here when you need to verify wording.
                </p>
                {citationDrawer.citations.map((cit, i) => {
                  const chunkTags = cit.chunk_id ? (citationTags[cit.chunk_id] ?? []) : []
                  return (
                    <div
                      key={i}
                      className="mb-3 rounded-2xl border border-white/10 bg-white/5 p-3.5"
                    >
                      <div className="mb-2 flex justify-between gap-2 text-[13px]">
                        <span className="font-semibold text-[var(--tc-text)]">Document</span>
                        <span className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-2 py-0.5 text-xs">
                          Snippet
                        </span>
                      </div>
                      <p className="text-[13px] leading-relaxed text-[var(--tc-muted)]">{cit.snippet || '—'}</p>
                      {chunkTags.length > 0 && (
                        <div className="mt-2">
                          <TagList tags={chunkTags} max={3} size="xs" />
                        </div>
                      )}
                    </div>
                  )
                })}
                <Button variant="ghost" className="w-full" onClick={() => setCitationDrawer(null)}>
                  Close drawer
                </Button>
              </div>
            ) : null}

            <div
              className="rounded-3xl border border-[var(--tc-border)] p-5"
              style={{ background: 'var(--tc-panel)', boxShadow: 'var(--tc-shadow)', backdropFilter: 'blur(20px)' }}
            >
              <h3 className="mb-2 text-lg font-semibold tracking-tight text-[var(--tc-text)]">Quick actions</h3>
              <p className="mb-4 text-[13px] leading-relaxed text-[var(--tc-muted)]">
                Every major function is reachable without hunting through menus.
              </p>
              <div className="grid gap-3">
                <Link
                  href="/dashboard/documents"
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-3.5 py-3 text-[13px] text-[var(--tc-text)] hover:bg-white/10"
                >
                  <div>
                    <div>Upload evidence</div>
                    <div className="mt-0.5 text-xs text-[var(--tc-muted)]">Drag PDF, DOCX, XLSX</div>
                  </div>
                  <span className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">Docs</span>
                </Link>
                <Link
                  href="/dashboard/questionnaires"
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-3.5 py-3 text-[13px] text-[var(--tc-text)] hover:bg-white/10"
                >
                  <div>
                    <div>Upload questionnaire</div>
                    <div className="mt-0.5 text-xs text-[var(--tc-muted)]">Parse and preview instantly</div>
                  </div>
                  <span className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">Qnrs</span>
                </Link>
                <Link
                  href="/dashboard/questionnaires"
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-3.5 py-3 text-[13px] text-[var(--tc-text)] hover:bg-white/10"
                >
                  <div>
                    <div>Continue review</div>
                    <div className="mt-0.5 text-xs text-[var(--tc-muted)]">Jump back into the last draft</div>
                  </div>
                  <span className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs">Open</span>
                </Link>
              </div>
            </div>

            {exportRecords.length > 0 && (
              <div
                className="rounded-3xl border border-[var(--tc-border)] p-5"
                style={{ background: 'var(--tc-panel)', boxShadow: 'var(--tc-shadow)' }}
              >
                <h3 className="mb-3 text-[13px] font-semibold uppercase tracking-wider text-[var(--tc-muted)]">
                  Recent exports
                </h3>
                <ul className="space-y-2">
                  {exportRecords.slice(0, 5).map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
                      <span className="truncate text-[var(--tc-text)]">{r.filename}</span>
                      {canExport && (
                        <Button size="sm" variant="ghost" onClick={() => handleDownload(r.id, r.filename)}>
                          Download
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      </div>

      <Modal isOpen={!!citationDrawer} onClose={() => setCitationDrawer(null)} title="Supporting evidence">
        {citationDrawer && (
          <div className="space-y-4">
            <p className="text-sm text-[var(--tc-muted)]">{citationDrawer.questionText}</p>
            <div className="max-h-[60vh] space-y-3 overflow-y-auto">
              {citationDrawer.citations.map((cit, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-white/10 bg-white/5 p-3 text-sm text-[var(--tc-text)]"
                >
                  {cit.snippet || '—'}
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>

      {exportReadyToast && (
        <Toast
          title="Export ready — Download"
          message={`${exportReadyToast.filename} has been generated with preserved formatting and evidence-backed answers.`}
          type="success"
          onDismiss={() => setExportReadyToast(null)}
        />
      )}
      {genSuccessToast && (
        <Toast
          title="Draft answers ready"
          message="New or updated drafts appear in the table. Review supporting evidence, edit text if needed, then approve and export when ready."
          type="success"
          onDismiss={() => setGenSuccessToast(false)}
        />
      )}
      {errorToast && (
        <Toast
          title="Error"
          message={errorToast}
          type="error"
          onDismiss={() => setErrorToast(null)}
        />
      )}
    </div>
  )
}
