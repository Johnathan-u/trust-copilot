'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import {
  Button,
  Card,
  CategoryChipsRow,
  CreatedTimestampText,
  Dialog,
  DisplayIdText,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  QuestionnaireListSkeleton,
  RegistryRowActionsMenu,
  Toast,
} from '@/components/ui'
import type { RowAction } from '@/components/ui/RegistryRowActionsMenu'
import { useAuth } from '@/contexts/AuthContext'
import {
  mutationFailureNotice,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import { actionVerb, confirmedActionNotice } from '@/lib/action-copy'
import { listLoadFlags } from '@/lib/render-state'
import { failureOf, isAbortError, readSectionJson } from '@/lib/section-load'
import {
  FRAMEWORK_OPTIONS,
  SUBJECT_AREA_OPTIONS,
  normalizeLabels,
} from '@/lib/listMetadata'
import { dialogAttributes } from '@/lib/dialog'
import { jobsHref, parseJobHistory } from '@/lib/job-history-consumer'

type Qnr = {
  id: number
  display_id: string
  filename: string
  status: string
  created_at: string | null
  deleted_at?: string | null
  frameworks?: string[]
  subject_areas?: string[]
  parse_metadata?: string | Record<string, unknown> | null
  question_count?: number
  review_reviewed?: number
  review_total?: number
  mapping_ambiguous?: boolean
  mapping_confirmation_url?: string | null
  job_id?: number
  job_status?: string
  job_progress?: { generated?: unknown; total?: unknown } | null
  needs_review?: boolean
}

type ParseJob = { id: number; status: string }
type Counts = { generated: number; total: number }
type ParsePhase = 'queued' | 'parsed' | 'failed'
type ActiveDialog =
  | { kind: 'archive'; qnr: Qnr }
  | { kind: 'delete'; qnr: Qnr }
  | { kind: 'restore'; qnr: Qnr }
  | { kind: 'bulk' }
type Filters = {
  workspaceId: number
  search: string
  framework: string
  subjectArea: string
  status: string
  createdFrom: string
  createdTo: string
  archivedMode: string
  page: number
  sort: string
  order: string
}

type QuestionnairePage = {
  rows: Qnr[]
  total: number
}

/** Extensions accepted by FileService.ALLOWED_RAW_EXTENSIONS. */
const ACCEPT_ATTRIBUTE = '.pdf,.docx,.doc,.xlsx,.xls,.txt'
const FORMAT_LINE = 'Accepted formats: PDF, DOCX, DOC, XLSX, XLS, and TXT.'
/** Documented default of MAX_UPLOAD_BYTES. The questionnaire API does not return it. */
const SIZE_LINE = 'Size limit: 50 MB.'
const WORKBOOK_CONTRACT =
  'Workbook contract: an XLSX or XLS answer cell is read from a header named Answer, Response, Reply, Vendor response, Vendor answer, or Answer text. The parser does not use the next column. A sheet with no answer header stores no answer cell. DOCX and PDF imports do not store a workbook answer cell. A new CSV upload is rejected. CSV parsing applies only to a file that is already stored with a .csv name.'
const PAGE_SIZE = 25
const LIST_CONTRACT =
  'The questionnaire list accepts page, page size, sort, and order. This screen requests one page of 25 and does not reorder that page in the browser.'
const SELECTION_SCOPE =
  'Selection applies to every questionnaire on this page for the current workspace. Changing the workspace, a filter, or the page clears it.'
const RETRY_NOTE =
  'There is no questionnaire reparse route. An administrator can retry a failed parse job from the questionnaire row. When the row has no job id, retry is offered only if that job is on the newest job page.'
const DELETE_NOTE =
  'Permanent deletion is not available. The questionnaire API archives a questionnaire and does not erase one questionnaire.'
const SEARCH_DEBOUNCE_MS = 300
const FIELD_CLASS =
  'w-full min-w-0 rounded-tc-xs border border-tc-border-strong bg-tc-surface-overlay px-tc-2 py-tc-2 text-tc-label text-tc-text'
const LABEL_CLASS = 'mb-tc-1 block text-tc-label font-medium text-tc-muted'
const STATUSES = [
  'uploaded',
  'parsed',
  'needs_review',
  'draft',
  'completed',
  'archived',
  'failed',
]
const SORTS = [
  { value: 'created_at', label: 'Created time' },
  { value: 'filename', label: 'Filename' },
  { value: 'status', label: 'Status' },
  { value: 'id', label: 'Id' },
] as const

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const onAbort = () => {
      window.clearTimeout(id)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const id = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

function readPositiveInt(data: unknown, key: string): number | null {
  if (!data || typeof data !== 'object') return null
  const value = (data as Record<string, unknown>)[key]
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : null
}

function readStatus(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null
  const status = (data as { status?: unknown }).status
  return typeof status === 'string' ? status : null
}

function acknowledged(data: unknown): boolean {
  return Boolean(
    data && typeof data === 'object' && (data as { ok?: unknown }).ok === true
  )
}

function countPair(data: unknown): Counts | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const generated = (data as { generated?: unknown }).generated
  const total = (data as { total?: unknown }).total
  if (
    typeof generated !== 'number' ||
    typeof total !== 'number' ||
    !Number.isSafeInteger(generated) ||
    !Number.isSafeInteger(total) ||
    generated < 0 ||
    total < 0 ||
    generated > total
  ) {
    return null
  }
  return { generated, total }
}

function readProgress(data: unknown): Counts | null {
  if (!data || typeof data !== 'object') return null
  return countPair((data as { progress?: unknown }).progress)
}

function wholeCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : null
}

function metadataRecord(
  value: Qnr['parse_metadata']
): Record<string, unknown> | null {
  if (!value) return null
  if (typeof value === 'object' && !Array.isArray(value)) return value
  if (typeof value !== 'string') return null
  try {
    const parsed = JSON.parse(value) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    return null
  }
  return null
}

function questionCount(row: Qnr): number | null {
  const explicit = wholeCount(row.question_count)
  if (explicit !== null) return explicit
  return wholeCount(metadataRecord(row.parse_metadata)?.count)
}

function reviewLine(row: Qnr): string {
  const reviewed = wholeCount(row.review_reviewed)
  const total = wholeCount(row.review_total)
  if (reviewed !== null && total !== null && reviewed <= total) {
    return `Review: ${reviewed} of ${total}`
  }
  return 'Review progress: Not reported'
}

function parseError(row: Qnr): string | null {
  const error = metadataRecord(row.parse_metadata)?.error
  if (typeof error !== 'string') return null
  const text = error.trim()
  if (!text || text.length > 500) return null
  return text
}

function sameOriginPath(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return null
  if (trimmed.includes('://') || trimmed.includes('\\')) return null
  return trimmed
}

function isoFromLocal(value: string): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

function listUrl(input: Filters): string {
  const params = new URLSearchParams({
    workspace_id: String(input.workspaceId),
  })
  if (input.search) params.set('search', input.search)
  if (input.framework) params.set('framework', input.framework)
  if (input.subjectArea) params.set('subject_area', input.subjectArea)
  if (input.status) params.set('status', input.status)
  const createdFrom = isoFromLocal(input.createdFrom)
  const createdTo = isoFromLocal(input.createdTo)
  if (createdFrom) params.set('created_from', createdFrom)
  if (createdTo) params.set('created_to', createdTo)
  params.set('archived', input.archivedMode)
  params.set('page', String(input.page))
  params.set('page_size', String(PAGE_SIZE))
  params.set('sort', input.sort)
  params.set('order', input.order)
  return `/api/questionnaires/?${params.toString()}`
}

function parseQuestionnairePage(data: unknown): QuestionnairePage {
  if (Array.isArray(data)) {
    return { rows: data as Qnr[], total: data.length }
  }
  if (
    data &&
    typeof data === 'object' &&
    Array.isArray((data as { items?: unknown }).items)
  ) {
    const record = data as { items: Qnr[]; total?: unknown }
    const total = wholeCount(record.total)
    return { rows: record.items, total: total ?? record.items.length }
  }
  throw new Error('malformed questionnaire list')
}

function statusLabel(status: string): string {
  if (status === 'failed') return 'Parsing failed'
  if (status === 'parsed') return 'Parsed'
  if (status === 'uploaded') return 'Uploaded'
  if (status === 'draft') return 'Draft'
  if (status === 'completed') return 'Completed'
  if (status === 'archived') return 'Archived'
  if (status === 'needs_review') return 'Needs review'
  return status
}

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value]
}

export default function QuestionnairesPage() {
  const { workspace, permissions, loading: authLoading } = useAuth()
  const workspaceId = workspace?.id
  const canEdit = permissions.can_edit
  const canAdmin = permissions.can_admin
  const [qnrs, setQnrs] = useState<Qnr[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [framework, setFramework] = useState('')
  const [subjectArea, setSubjectArea] = useState('')
  const [status, setStatus] = useState('')
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')
  const [archivedMode, setArchivedMode] = useState<
    'active' | 'include' | 'only'
  >('active')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('created_at')
  const [order, setOrder] = useState('desc')
  const [total, setTotal] = useState(0)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [parseJobs, setParseJobs] = useState<Map<number, ParseJob>>(new Map())
  const [jobProgress, setJobProgress] = useState<Map<number, Counts>>(new Map())
  const [parsePhase, setParsePhase] = useState<ParsePhase | null>(null)
  const [parseCounts, setParseCounts] = useState<Counts | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploadFrameworks, setUploadFrameworks] = useState<string[]>([])
  const [uploadSubjects, setUploadSubjects] = useState<string[]>([])
  const [uploadNotice, setUploadNotice] = useState<{
    title: string
    message: string
    type: 'success' | 'error'
  } | null>(null)
  const [dialog, setDialog] = useState<ActiveDialog | null>(null)
  const [metadataQnr, setMetadataQnr] = useState<Qnr | null>(null)
  const [preview, setPreview] = useState<{
    qnrId: number
    deps: Record<string, number | string>
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [retryingId, setRetryingId] = useState<number | null>(null)
  const [retryNotice, setRetryNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const generation = useRef(0)
  const parsePoll = useRef<AbortController | null>(null)
  const selectAllRef = useRef<HTMLInputElement>(null)

  const loadKey = [
    workspaceId ?? '',
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    page,
    sort,
    order,
    loadAttempt,
  ].join('\n')
  const [seenLoadKey, setSeenLoadKey] = useState<string | null>(null)
  if (!authLoading && seenLoadKey !== loadKey) {
    setSeenLoadKey(loadKey)
    const flags = listLoadFlags({
      enabled: workspaceId != null,
      hasRows: qnrs.length > 0,
    })
    if (flags.loading !== null) setLoading(flags.loading)
    setRefreshing(flags.refreshing)
    if (flags.clearFailure) setLoadFailure(null)
  }

  const selectionScopeKey = [
    workspaceId ?? '',
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    page,
    sort,
    order,
  ].join('\n')
  const [seenSelection, setSeenSelection] = useState<string | null>(null)
  if (seenSelection !== selectionScopeKey) {
    setSeenSelection(selectionScopeKey)
    if (seenSelection !== null) setSelectedIds(new Set())
  }

  const [seenWorkspace, setSeenWorkspace] = useState<number | null>(null)
  if ((workspaceId ?? null) !== seenWorkspace) {
    setSeenWorkspace(workspaceId ?? null)
    if (seenWorkspace !== null) {
      setParseJobs(new Map())
      setJobProgress(new Map())
      setParsePhase(null)
      setParseCounts(null)
      setRetryNotice(null)
    }
  }

  const filterKey = [
    workspaceId ?? '',
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
  ].join('\n')
  const [seenFilter, setSeenFilter] = useState<string | null>(null)
  if (seenFilter !== filterKey) {
    setSeenFilter(filterKey)
    if (seenFilter !== null && page !== 1) setPage(1)
  }

  const filters: Filters = {
    workspaceId: workspaceId ?? 0,
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    page,
    sort,
    order,
  }

  const loadJobs = useCallback(
    async (signal: AbortSignal, gen: number, rows: Qnr[]) => {
      if (workspaceId == null || rows.length === 0) {
        if (gen === generation.current) {
          setParseJobs(new Map())
          setJobProgress(new Map())
        }
        return
      }
      try {
        const response = await fetch(
          `/api/jobs?workspace_id=${workspaceId}&limit=25`,
          { credentials: 'include', signal, cache: 'no-store' }
        )
        if (!response.ok || signal.aborted || gen !== generation.current) return
        const history = parseJobHistory(await readSectionJson(response))
        if (signal.aborted || gen !== generation.current) return
        const nextJobs = new Map<number, ParseJob>()
        const nextProgress = new Map<number, Counts>()
        for (const row of rows) {
          const jobId = readPositiveInt(row, 'job_id')
          if (jobId && typeof row.job_status === 'string' && row.job_status) {
            nextJobs.set(row.id, { id: jobId, status: row.job_status })
          }
          const listed = countPair(row.job_progress)
          if (listed) nextProgress.set(row.id, listed)
        }
        for (const job of history.items) {
          if (job.objectRef?.type !== 'questionnaire') continue
          if (
            job.kind === 'parse_questionnaire' &&
            job.status &&
            !nextJobs.has(job.objectRef.id)
          ) {
            nextJobs.set(job.objectRef.id, { id: job.id, status: job.status })
          }
          if (job.progress && !nextProgress.has(job.objectRef.id)) {
            nextProgress.set(job.objectRef.id, job.progress)
          }
        }
        setParseJobs(nextJobs)
        setJobProgress(nextProgress)
      } catch (error) {
        if (isAbortError(error) || signal.aborted) return
        if (gen === generation.current) {
          setParseJobs(new Map())
          setJobProgress(new Map())
        }
      }
    },
    [workspaceId]
  )

  useEffect(() => {
    if (workspaceId == null) return
    const controller = new AbortController()
    const gen = ++generation.current
    const url = listUrl({
      workspaceId,
      search,
      framework,
      subjectArea,
      status,
      createdFrom,
      createdTo,
      archivedMode,
      page,
      sort,
      order,
    })
    void (async () => {
      await Promise.resolve()
      if (controller.signal.aborted) return
      try {
        const response = await fetch(url, {
          credentials: 'include',
          signal: controller.signal,
          cache: 'no-store',
        })
        const data = await readSectionJson(response)
        const listed = parseQuestionnairePage(data)
        if (controller.signal.aborted || gen !== generation.current) return
        setQnrs(listed.rows)
        setTotal(listed.total)
        setLoadFailure(null)
        void loadJobs(controller.signal, gen, listed.rows)
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) return
        if (gen !== generation.current) return
        setQnrs([])
        setTotal(0)
        setParseJobs(new Map())
        setJobProgress(new Map())
        setLoadFailure(failureOf(error))
      } finally {
        if (!controller.signal.aborted && gen === generation.current) {
          setLoading(false)
          setRefreshing(false)
        }
      }
    })()
    return () => controller.abort()
  }, [
    workspaceId,
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    page,
    sort,
    order,
    loadAttempt,
    loadJobs,
  ])

  useEffect(() => {
    const id = window.setTimeout(() => {
      setSearch(searchInput.trim())
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [searchInput])

  useEffect(() => {
    return () => {
      parsePoll.current?.abort()
    }
  }, [workspaceId])

  const activeQnrs = qnrs.filter((row) => !row.deleted_at)
  const selectAll =
    activeQnrs.length > 0 && activeQnrs.every((row) => selectedIds.has(row.id))
  const selectSome = activeQnrs.some((row) => selectedIds.has(row.id))
  useEffect(() => {
    const element = selectAllRef.current
    if (element) element.indeterminate = selectSome && !selectAll
  }, [selectSome, selectAll])

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const narrowed = Boolean(
    search ||
    framework ||
    subjectArea ||
    status ||
    createdFrom ||
    createdTo ||
    archivedMode !== 'active'
  )

  const clearSearch = () => {
    setSearchInput('')
    setSearch('')
  }

  const chips: Array<{
    id: string
    label: string
    removeName: string
    onRemove: () => void
  }> = []
  if (searchInput.trim()) {
    chips.push({
      id: 'search',
      label: searchInput.trim(),
      removeName: searchInput.trim(),
      onRemove: clearSearch,
    })
  }
  if (framework) {
    chips.push({
      id: 'framework',
      label: framework,
      removeName: framework,
      onRemove: () => setFramework(''),
    })
  }
  if (subjectArea) {
    chips.push({
      id: 'subject',
      label: subjectArea,
      removeName: subjectArea,
      onRemove: () => setSubjectArea(''),
    })
  }
  if (createdFrom) {
    chips.push({
      id: 'from',
      label: 'Created from',
      removeName: 'Created from',
      onRemove: () => setCreatedFrom(''),
    })
  }
  if (createdTo) {
    chips.push({
      id: 'to',
      label: 'Created to',
      removeName: 'Created to',
      onRemove: () => setCreatedTo(''),
    })
  }
  if (status) {
    chips.push({
      id: 'status',
      label: status,
      removeName: status,
      onRemove: () => setStatus(''),
    })
  }
  if (archivedMode !== 'active') {
    const label = archivedMode === 'only' ? 'Archived only' : 'Include archived'
    chips.push({
      id: 'archived',
      label,
      removeName: label,
      onRemove: () => setArchivedMode('active'),
    })
  }

  const watchParse = async (jobId: number, qnrId: number, active: Filters) => {
    if (workspaceId == null) return
    parsePoll.current?.abort()
    const controller = new AbortController()
    parsePoll.current = controller
    const url = listUrl(active)
    try {
      for (let attempt = 0; attempt < 6; attempt += 1) {
        const response = await fetch(
          `/api/jobs/${jobId}?workspace_id=${workspaceId}`,
          {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          }
        )
        if (controller.signal.aborted) return
        if (!response.ok) return
        const payload = await response.json().catch(() => null)
        const jobStatus = readStatus(payload)
        if (jobStatus === 'queued' || jobStatus === 'running') {
          setParsePhase('queued')
          const running = await fetch(url, {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          })
          if (!controller.signal.aborted && running.ok) {
            const parsed = parseQuestionnairePage(
              await readSectionJson(running)
            )
            const row = parsed.rows.find((item) => item.id === qnrId)
            const progress =
              readProgress(payload) ?? countPair(row?.job_progress)
            if (progress) setParseCounts(progress)
          }
          await delay(1000, controller.signal)
          continue
        }
        if (jobStatus === 'failed' || jobStatus === 'cancelled') {
          setParsePhase('failed')
          setParseCounts(readProgress(payload))
          return
        }
        if (jobStatus === 'completed') {
          const listed = await fetch(url, {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          })
          const parsed = parseQuestionnairePage(await readSectionJson(listed))
          if (controller.signal.aborted) return
          setQnrs(parsed.rows)
          setTotal(parsed.total)
          const row = parsed.rows.find((item) => item.id === qnrId)
          if (row?.status === 'parsed') setParsePhase('parsed')
          else if (row?.status === 'failed') setParsePhase('failed')
          else setParsePhase('queued')
          setParseCounts(readProgress(payload) ?? countPair(row?.job_progress))
          return
        }
        return
      }
    } catch (error) {
      if (!isAbortError(error)) return
    }
  }

  const confirmUpload = () => {
    if (!uploadFile || workspaceId == null) return
    const file = uploadFile
    const active = filters
    setUploading(true)
    setUploadModalOpen(false)
    setUploadNotice(null)
    setParsePhase(null)
    setParseCounts(null)
    const body = new FormData()
    body.append('workspace_id', String(workspaceId))
    body.append('file', file)
    if (uploadFrameworks.length > 0) {
      body.append('frameworks', uploadFrameworks.join(','))
    }
    if (uploadSubjects.length > 0) {
      body.append('subject_areas', uploadSubjects.join(','))
    }
    void fetch('/api/questionnaires/upload', {
      method: 'POST',
      credentials: 'include',
      body,
    })
      .then(async (response) => {
        const data = await response.json().catch(() => null)
        if (!response.ok) {
          const notice = mutationFailureNotice(
            response.status,
            data,
            'The file was not stored. Try again.'
          )
          setUploadNotice({ ...notice, type: 'error' })
          return
        }
        setUploadNotice({
          ...confirmedActionNotice('upload'),
          type: 'success',
        })
        const jobId = readPositiveInt(data, 'job_id')
        const qnrId = readPositiveInt(data, 'id')
        if (jobId && qnrId) void watchParse(jobId, qnrId, active)
        else setLoadAttempt((value) => value + 1)
      })
      .catch(() =>
        setUploadNotice({
          title: 'Could not complete that',
          message: 'The file was not stored. Try again.',
          type: 'error',
        })
      )
      .finally(() => {
        setUploading(false)
        setUploadFile(null)
      })
  }

  const openArchive = (row: Qnr) => {
    if (workspaceId == null) return
    const qnrId = row.id
    setMetadataQnr(null)
    setDialog({ kind: 'archive', qnr: row })
    setPreview(null)
    setOutcome(null)
    setDialogError(null)
    void fetch(
      `/api/questionnaires/${qnrId}/delete-preview?workspace_id=${workspaceId}`,
      { credentials: 'include' }
    )
      .then(async (response) => (response.ok ? response.json() : null))
      .then((data: unknown) => {
        if (!data || typeof data !== 'object') return
        const dependencies = (data as { dependencies?: unknown }).dependencies
        if (dependencies && typeof dependencies === 'object') {
          setPreview({
            qnrId,
            deps: dependencies as Record<string, number | string>,
          })
        }
      })
      .catch(() => {})
  }

  const confirmArchive = async () => {
    if (workspaceId == null || dialog?.kind !== 'archive') return
    setBusy(true)
    setOutcome(null)
    setDialogError(null)
    try {
      const response = await fetch(
        `/api/questionnaires/${dialog.qnr.id}?workspace_id=${workspaceId}`,
        { method: 'DELETE', credentials: 'include' }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || !acknowledged(data)) {
        setDialogError(
          mutationFailureNotice(
            response.status,
            data,
            'The questionnaire was not archived. Try again.'
          ).message
        )
        return
      }
      setOutcome('Archived.')
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The questionnaire was not archived. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const confirmRestore = async () => {
    if (workspaceId == null || dialog?.kind !== 'restore') return
    setBusy(true)
    setOutcome(null)
    setDialogError(null)
    try {
      const response = await fetch(
        `/api/questionnaires/${dialog.qnr.id}/restore?workspace_id=${workspaceId}`,
        { method: 'POST', credentials: 'include' }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || !acknowledged(data)) {
        setDialogError(
          mutationFailureNotice(
            response.status,
            data,
            'The questionnaire was not restored. Try again.'
          ).message
        )
        return
      }
      setOutcome('Restored.')
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The questionnaire was not restored. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const confirmBulk = async () => {
    if (workspaceId == null || selectedIds.size === 0) return
    setBusy(true)
    setOutcome(null)
    setDialogError(null)
    try {
      const response = await fetch(
        `/api/questionnaires/bulk-delete?workspace_id=${workspaceId}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: Array.from(selectedIds) }),
        }
      )
      const data = (await response.json().catch(() => null)) as {
        deleted?: unknown
      } | null
      if (!response.ok || !data || typeof data.deleted !== 'number') {
        setDialogError(
          mutationFailureNotice(
            response.status,
            data,
            'The questionnaires were not archived. Try again.'
          ).message
        )
        return
      }
      setOutcome('Archived.')
      setSelectedIds(new Set())
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The questionnaires were not archived. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const retryParse = async (row: Qnr, job: ParseJob) => {
    if (workspaceId == null) return
    setRetryingId(row.id)
    setRetryNotice(null)
    setActionError(null)
    try {
      const response = await fetch(
        `/api/jobs/${job.id}/retry?workspace_id=${workspaceId}`,
        { method: 'POST', credentials: 'include' }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || readStatus(data) !== 'queued') {
        setActionError(
          mutationFailureNotice(
            response.status,
            data,
            'Parsing was not queued. Try again.'
          ).message
        )
        return
      }
      setRetryNotice(`Parsing queued for ${row.display_id}`)
    } catch {
      setActionError('Parsing was not queued. Try again.')
    } finally {
      setRetryingId(null)
    }
  }

  const closeDialog = () => {
    if (busy) return
    setDialog(null)
    setOutcome(null)
    setDialogError(null)
  }

  const selectedCount = selectedIds.size
  const archiveQnr = dialog?.kind === 'archive' ? dialog.qnr : null
  const shownDeps =
    preview && archiveQnr && preview.qnrId === archiveQnr.id ? preview.deps : {}
  const deleteQnr = dialog?.kind === 'delete' ? dialog.qnr : null
  const restoreQnr = dialog?.kind === 'restore' ? dialog.qnr : null

  return (
    <div className="min-w-0 max-w-full overflow-x-hidden p-tc-4 sm:p-tc-7">
      <div className="mb-tc-4 flex min-w-0 items-center gap-tc-3">
        <h1 className="text-tc-headline font-semibold text-tc-text">
          Questionnaires
        </h1>
        {refreshing && !loading && (
          <span
            aria-hidden="true"
            className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-tc-border border-t-tc-primary"
          />
        )}
      </div>
      {workspaceId != null && (
        <p className="mb-tc-4 max-w-3xl text-tc-label text-tc-muted">
          {LIST_CONTRACT}
        </p>
      )}
      {canEdit && workspaceId != null && (
        <p className="mb-tc-4 max-w-3xl text-tc-label text-tc-text">
          {SELECTION_SCOPE}
        </p>
      )}
      {workspaceId != null && (
        <p className="mb-tc-4 max-w-3xl break-words text-tc-label text-tc-muted">
          {RETRY_NOTE}
        </p>
      )}
      {workspaceId != null && (
        <div className="mb-tc-4 max-w-3xl space-y-tc-2 break-words text-tc-label text-tc-muted">
          <p id="qnr-upload-constraints">
            {FORMAT_LINE} {SIZE_LINE} This is the server default. The
            questionnaire API does not return the configured limit.
          </p>
          <p>{WORKBOOK_CONTRACT}</p>
        </div>
      )}
      {canEdit && (
        <Card className="mb-tc-4">
          <input
            id="qnr-upload"
            type="file"
            className="hidden"
            accept={ACCEPT_ATTRIBUTE}
            aria-describedby="qnr-upload-constraints"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (!file) return
              event.target.value = ''
              setUploadFile(file)
              setUploadFrameworks([])
              setUploadSubjects([])
              setUploadModalOpen(true)
            }}
            disabled={uploading}
          />
          <Button
            type="button"
            loading={uploading}
            aria-describedby="qnr-upload-constraints"
            data-upload-state={uploading ? 'pending' : 'idle'}
            onClick={() => document.getElementById('qnr-upload')?.click()}
          >
            {uploading
              ? actionVerb('upload', 'pending')
              : actionVerb('upload', 'idle')}
          </Button>
          <p className="mt-tc-3 text-tc-label text-tc-text">
            Parsing progress:{' '}
            {parseCounts
              ? `${parseCounts.generated} of ${parseCounts.total}`
              : 'Not reported'}
          </p>
          {parsePhase && (
            <p
              role="status"
              data-parse-progress={parsePhase}
              className="mt-tc-2 text-tc-label text-tc-text"
            >
              {parsePhase === 'queued'
                ? 'Queued'
                : parsePhase === 'parsed'
                  ? 'Parsed'
                  : 'Failed'}
            </p>
          )}
        </Card>
      )}
      {workspaceId != null && (
        <Card className="mb-tc-4">
          <div className="grid grid-cols-1 gap-tc-3 md:grid-cols-2 xl:grid-cols-3">
            <Input
              id="qnr-search"
              label="Search questionnaires"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="ID, filename, framework, subject, or status"
            />
            <div className="min-w-0">
              <label htmlFor="qnr-framework" className={LABEL_CLASS}>
                Framework
              </label>
              <select
                id="qnr-framework"
                className={FIELD_CLASS}
                value={framework}
                onChange={(event) => setFramework(event.target.value)}
              >
                <option value="">All frameworks</option>
                {FRAMEWORK_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-subject" className={LABEL_CLASS}>
                Subject area
              </label>
              <select
                id="qnr-subject"
                className={FIELD_CLASS}
                value={subjectArea}
                onChange={(event) => setSubjectArea(event.target.value)}
              >
                <option value="">All subject areas</option>
                {SUBJECT_AREA_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-created-from" className={LABEL_CLASS}>
                Created from
              </label>
              <input
                id="qnr-created-from"
                type="datetime-local"
                className={FIELD_CLASS}
                value={createdFrom}
                onChange={(event) => setCreatedFrom(event.target.value)}
              />
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-created-to" className={LABEL_CLASS}>
                Created to
              </label>
              <input
                id="qnr-created-to"
                type="datetime-local"
                className={FIELD_CLASS}
                value={createdTo}
                onChange={(event) => setCreatedTo(event.target.value)}
              />
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-status" className={LABEL_CLASS}>
                Questionnaire status
              </label>
              <select
                id="qnr-status"
                className={FIELD_CLASS}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="">All statuses</option>
                {STATUSES.map((option) => (
                  <option key={option} value={option}>
                    {statusLabel(option)}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-archived" className={LABEL_CLASS}>
                Archive filter
              </label>
              <select
                id="qnr-archived"
                className={FIELD_CLASS}
                value={archivedMode}
                onChange={(event) =>
                  setArchivedMode(
                    event.target.value as 'active' | 'include' | 'only'
                  )
                }
              >
                <option value="active">Active only</option>
                <option value="include">Include archived</option>
                <option value="only">Archived only</option>
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-sort" className={LABEL_CLASS}>
                Sort by
              </label>
              <select
                id="qnr-sort"
                className={FIELD_CLASS}
                value={sort}
                onChange={(event) => {
                  setSort(event.target.value)
                  setPage(1)
                }}
              >
                {SORTS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="qnr-order" className={LABEL_CLASS}>
                Sort order
              </label>
              <select
                id="qnr-order"
                className={FIELD_CLASS}
                value={order}
                onChange={(event) => {
                  setOrder(event.target.value)
                  setPage(1)
                }}
              >
                <option value="desc">Descending</option>
                <option value="asc">Ascending</option>
              </select>
            </div>
          </div>
          <nav
            aria-label="Questionnaire pages"
            className="mt-tc-3 flex flex-wrap items-center gap-tc-2"
          >
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              Previous page
            </Button>
            <span className="text-tc-label text-tc-muted">
              Page {page} of {pageCount}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={page >= pageCount}
              onClick={() => setPage((value) => value + 1)}
            >
              Next page
            </Button>
          </nav>
          {chips.length > 0 && (
            <div className="mt-tc-3 flex flex-wrap gap-tc-2">
              {chips.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  className="inline-flex min-h-11 max-w-full items-center break-all rounded-full border border-tc-border px-tc-3 py-tc-1 text-tc-label text-tc-text"
                  aria-label={`Remove ${chip.removeName} filter`}
                  onClick={chip.onRemove}
                >
                  {chip.label}
                </button>
              ))}
            </div>
          )}
        </Card>
      )}
      <Card>
        {loadFailure ? (
          <ErrorState
            failure={loadFailure}
            onRetry={() => setLoadAttempt((value) => value + 1)}
          />
        ) : loading ? (
          <LoadingState
            label="Loading questionnaires"
            resetKey={loadAttempt}
            onRetry={() => setLoadAttempt((value) => value + 1)}
          >
            <QuestionnaireListSkeleton />
          </LoadingState>
        ) : qnrs.length === 0 ? (
          <EmptyState
            title={
              narrowed ? 'No matching questionnaires' : 'No questionnaires yet'
            }
            description={
              narrowed
                ? 'No questionnaire in this workspace matches the current filters.'
                : canEdit
                  ? 'Upload a questionnaire to start parsing and review.'
                  : 'Ask an editor to upload questionnaires.'
            }
            action={
              canEdit && !narrowed ? (
                <Button
                  type="button"
                  onClick={() => document.getElementById('qnr-upload')?.click()}
                >
                  Upload your first questionnaire
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            {canEdit && selectedCount > 0 && (
              <div className="mb-tc-3 flex flex-wrap items-center justify-between gap-tc-2 rounded-tc border border-tc-border bg-tc-surface-raised px-tc-3 py-tc-2">
                <span className="text-tc-label text-tc-text">
                  {selectedCount}{' '}
                  {selectedCount === 1 ? 'questionnaire' : 'questionnaires'}{' '}
                  selected in this result
                </span>
                <div className="flex flex-wrap gap-tc-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedIds(new Set())}
                  >
                    Clear selection
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    onClick={() => {
                      setOutcome(null)
                      setDialogError(null)
                      setDialog({ kind: 'bulk' })
                    }}
                  >
                    Archive selected
                  </Button>
                </div>
              </div>
            )}
            {canEdit && activeQnrs.length > 0 && (
              <div className="flex items-center gap-tc-2 border-b border-tc-border py-tc-2 text-tc-label text-tc-muted">
                <label className="flex min-h-11 cursor-pointer items-center gap-tc-2">
                  <input
                    type="checkbox"
                    checked={selectAll}
                    ref={selectAllRef}
                    onChange={() => {
                      setSelectedIds(
                        selectAll
                          ? new Set()
                          : new Set(activeQnrs.map((row) => row.id))
                      )
                    }}
                    aria-label="Select all questionnaires in this result"
                    className="h-4 w-4 rounded border-tc-border"
                  />
                  Select all questionnaires in this result
                </label>
              </div>
            )}
            <ul
              aria-label="Questionnaires"
              className="min-w-0 divide-y divide-tc-border"
            >
              {qnrs.map((row) => {
                const job = parseJobs.get(row.id) ?? null
                const progress = jobProgress.get(row.id) ?? null
                const questions = questionCount(row)
                const errorText = parseError(row)
                const confirmation =
                  row.mapping_ambiguous === true
                    ? sameOriginPath(row.mapping_confirmation_url)
                    : null
                const canRetry =
                  canAdmin &&
                  job !== null &&
                  (job.status === 'failed' || job.status === 'cancelled') &&
                  !row.deleted_at
                const actions: RowAction[] = [
                  {
                    id: 'copy_id',
                    label: 'Copy ID',
                    onClick: () => {
                      void navigator.clipboard?.writeText(row.display_id)
                    },
                  },
                  {
                    id: 'open',
                    label: 'Open',
                    href: `/dashboard/review/${row.id}`,
                  },
                  {
                    id: 'edit_metadata',
                    label: 'Edit metadata',
                    onClick: () => {
                      setDialog(null)
                      setMetadataQnr(row)
                    },
                  },
                ]
                if (row.deleted_at) {
                  actions.push({
                    id: 'restore',
                    label: 'Restore',
                    onClick: () => {
                      setMetadataQnr(null)
                      setOutcome(null)
                      setDialogError(null)
                      setDialog({ kind: 'restore', qnr: row })
                    },
                  })
                } else {
                  actions.push(
                    {
                      id: 'archive',
                      label: 'Archive',
                      onClick: () => openArchive(row),
                    },
                    {
                      id: 'delete',
                      label: 'Delete',
                      onClick: () => {
                        setMetadataQnr(null)
                        setOutcome(null)
                        setDialogError(null)
                        setDialog({ kind: 'delete', qnr: row })
                      },
                    }
                  )
                }
                return (
                  <li
                    key={row.id}
                    className="flex min-w-0 flex-col gap-tc-3 py-tc-3 sm:flex-row sm:items-start"
                  >
                    {canEdit && (
                      <div className="pt-tc-1">
                        {!row.deleted_at ? (
                          <input
                            type="checkbox"
                            checked={selectedIds.has(row.id)}
                            onChange={() => {
                              setSelectedIds((current) => {
                                const next = new Set(current)
                                if (next.has(row.id)) next.delete(row.id)
                                else next.add(row.id)
                                return next
                              })
                            }}
                            aria-label={`Select ${row.display_id}`}
                            className="h-4 w-4 rounded border-tc-border"
                          />
                        ) : (
                          <span className="inline-block h-4 w-4" aria-hidden />
                        )}
                      </div>
                    )}
                    <div className="min-w-0 flex-1 space-y-tc-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-tc-2">
                        <Link
                          href={`/dashboard/questionnaires/${row.id}`}
                          className="min-w-0 break-all font-medium text-tc-text"
                        >
                          {row.filename}
                        </Link>
                        <span className="rounded-tc-xs border border-tc-border px-tc-2 py-tc-1 text-tc-caption text-tc-muted">
                          {statusLabel(row.status)}
                        </span>
                        {row.deleted_at && (
                          <span
                            className="rounded-tc-xs border px-tc-2 py-tc-1 text-tc-caption"
                            style={{
                              background: 'var(--tc-warning-surface)',
                              color: 'var(--tc-warning)',
                              borderColor: 'var(--tc-warning)',
                            }}
                          >
                            Archived
                          </span>
                        )}
                      </div>
                      <div className="flex min-w-0 flex-wrap items-center gap-tc-2">
                        <DisplayIdText value={row.display_id} />
                        <CreatedTimestampText value={row.created_at} />
                      </div>
                      <CategoryChipsRow
                        frameworks={normalizeLabels(row.frameworks)}
                        subjectAreas={normalizeLabels(row.subject_areas)}
                      />
                      <p className="break-words text-tc-label text-tc-text">
                        Questions:{' '}
                        {questions === null ? 'Not reported' : questions}
                      </p>
                      <p className="break-words text-tc-label text-tc-text">
                        {reviewLine(row)}
                      </p>
                      <p className="break-words text-tc-label text-tc-text">
                        Job progress:{' '}
                        {progress
                          ? `${progress.generated} of ${progress.total}`
                          : 'Not reported'}
                      </p>
                      {row.mapping_ambiguous === true ? (
                        confirmation ? (
                          <Link
                            href={confirmation}
                            className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
                          >
                            Confirm mapping
                          </Link>
                        ) : (
                          <div className="space-y-tc-1">
                            <p className="text-tc-label text-tc-muted">
                              Mapping confirmation is not available.
                            </p>
                            <Button type="button" size="sm" disabled>
                              Confirm mapping
                            </Button>
                          </div>
                        )
                      ) : (
                        <p className="text-tc-label text-tc-text">
                          Mapping:{' '}
                          {row.mapping_ambiguous === false
                            ? 'Not ambiguous'
                            : 'Not reported'}
                        </p>
                      )}
                      <Link
                        href={`/dashboard/review/${row.id}`}
                        className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
                      >
                        Review answers
                      </Link>
                      {job && workspaceId != null && (
                        <Link
                          href={jobsHref(workspaceId)}
                          className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
                        >
                          View parse job {job.id}
                        </Link>
                      )}
                      {errorText && (
                        <p className="break-words text-tc-label text-tc-muted">
                          {errorText}
                        </p>
                      )}
                      {canRetry && job && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={retryingId === row.id}
                          aria-busy={retryingId === row.id}
                          onClick={() => void retryParse(row, job)}
                        >
                          {retryingId === row.id
                            ? 'Retrying'
                            : `Retry parsing for ${row.display_id}`}
                        </Button>
                      )}
                      {retryNotice?.endsWith(row.display_id) && (
                        <p className="text-tc-label text-tc-text">
                          {retryNotice}
                        </p>
                      )}
                    </div>
                    {canEdit && (
                      <div className="shrink-0">
                        <RegistryRowActionsMenu
                          aria-label={`Actions for ${row.display_id}`}
                          actions={actions}
                        />
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </>
        )}
        {actionError && (
          <p role="alert" className="mt-tc-3 text-tc-label text-tc-danger">
            {actionError}
          </p>
        )}
      </Card>
      <Dialog
        open={Boolean(archiveQnr)}
        onClose={closeDialog}
        title="Archive questionnaire?"
        description="Archiving hides this questionnaire from the active list. It can be restored. This is not permanent deletion."
        role="alertdialog"
        closeDisabled={busy}
      >
        {archiveQnr && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {archiveQnr.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {archiveQnr.display_id}
            </p>
            {Object.entries(shownDeps).some(
              ([, value]) => typeof value === 'number' && value > 0
            ) && (
              <ul className="text-tc-label text-tc-text">
                {Object.entries(shownDeps)
                  .filter(([, value]) => typeof value === 'number' && value > 0)
                  .map(([key, value]) => (
                    <li key={key}>
                      {value} {key.replace(/_/g, ' ')}
                    </li>
                  ))}
              </ul>
            )}
            {dialogError && (
              <p role="alert" className="text-tc-label text-tc-danger">
                {dialogError}
              </p>
            )}
            {outcome && (
              <p role="status" className="text-tc-label text-tc-text">
                {outcome}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-tc-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={closeDialog}
                disabled={busy}
                {...{
                  [dialogAttributes.initial]: dialogAttributes.initialDismiss,
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="danger"
                size="sm"
                onClick={() => void confirmArchive()}
                disabled={busy || Boolean(outcome)}
              >
                {busy ? 'Archiving' : 'Archive'}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
      <Dialog
        open={Boolean(deleteQnr)}
        onClose={closeDialog}
        title="Delete record?"
        description={DELETE_NOTE}
        role="alertdialog"
      >
        {deleteQnr && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {deleteQnr.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {deleteQnr.display_id}
            </p>
            <div className="flex flex-wrap justify-end gap-tc-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={closeDialog}
                {...{
                  [dialogAttributes.initial]: dialogAttributes.initialDismiss,
                }}
              >
                Cancel
              </Button>
              <Button type="button" variant="danger" size="sm" disabled>
                Delete permanently
              </Button>
            </div>
          </div>
        )}
      </Dialog>
      <Dialog
        open={Boolean(restoreQnr)}
        onClose={closeDialog}
        title="Restore questionnaire?"
        description="Restoring returns this archived questionnaire to the active list after the server accepts it."
        role="alertdialog"
        closeDisabled={busy}
      >
        {restoreQnr && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {restoreQnr.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {restoreQnr.display_id}
            </p>
            {dialogError && (
              <p role="alert" className="text-tc-label text-tc-danger">
                {dialogError}
              </p>
            )}
            {outcome && (
              <p role="status" className="text-tc-label text-tc-text">
                {outcome}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-tc-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={closeDialog}
                disabled={busy}
                {...{
                  [dialogAttributes.initial]: dialogAttributes.initialDismiss,
                }}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => void confirmRestore()}
                disabled={busy || Boolean(outcome)}
              >
                {busy ? 'Restoring' : 'Restore'}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
      <Dialog
        open={dialog?.kind === 'bulk'}
        onClose={closeDialog}
        title="Archive selected questionnaires?"
        description="Archiving hides the selected questionnaires from the active list. They can be restored. This is not permanent deletion."
        role="alertdialog"
        closeDisabled={busy}
      >
        <div className="space-y-tc-3">
          <p className="break-words text-tc-label text-tc-muted">
            {qnrs
              .filter((row) => selectedIds.has(row.id))
              .map((row) => row.display_id)
              .join(', ')}
          </p>
          {dialogError && (
            <p role="alert" className="text-tc-label text-tc-danger">
              {dialogError}
            </p>
          )}
          {outcome && (
            <p role="status" className="text-tc-label text-tc-text">
              {outcome}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-tc-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={closeDialog}
              disabled={busy}
              {...{
                [dialogAttributes.initial]: dialogAttributes.initialDismiss,
              }}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              onClick={() => void confirmBulk()}
              disabled={busy || Boolean(outcome)}
            >
              {busy ? 'Archiving' : 'Archive'}
            </Button>
          </div>
        </div>
      </Dialog>
      {metadataQnr && workspaceId != null && (
        <MetadataDialog
          qnr={metadataQnr}
          workspaceId={workspaceId}
          onClose={() => setMetadataQnr(null)}
          onSaved={(id, frameworks, subjectAreas) => {
            setQnrs((current) =>
              current.map((row) =>
                row.id === id
                  ? {
                      ...row,
                      frameworks,
                      subject_areas: subjectAreas,
                    }
                  : row
              )
            )
            setMetadataQnr((current) =>
              current && current.id === id
                ? {
                    ...current,
                    frameworks,
                    subject_areas: subjectAreas,
                  }
                : current
            )
          }}
        />
      )}
      <Dialog
        open={uploadModalOpen}
        onClose={() => {
          if (uploading) return
          setUploadModalOpen(false)
          setUploadFile(null)
        }}
        title="Upload questionnaire"
      >
        <div className="space-y-tc-4">
          <p className="break-all text-tc-label text-tc-text">
            {uploadFile?.name}
          </p>
          <div>
            <p className="mb-tc-2 text-tc-caption font-medium uppercase tracking-wide text-tc-muted">
              Frameworks
            </p>
            <div className="flex flex-wrap gap-tc-2">
              {FRAMEWORK_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() =>
                    setUploadFrameworks((current) =>
                      toggleValue(current, option)
                    )
                  }
                  className={`rounded-full border px-tc-3 py-tc-1 text-tc-caption ${
                    uploadFrameworks.includes(option)
                      ? 'border-tc-primary text-tc-primary'
                      : 'border-tc-border text-tc-muted'
                  }`}
                  aria-pressed={uploadFrameworks.includes(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="mb-tc-2 text-tc-caption font-medium uppercase tracking-wide text-tc-muted">
              Subject areas
            </p>
            <div className="flex flex-wrap gap-tc-2">
              {SUBJECT_AREA_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() =>
                    setUploadSubjects((current) => toggleValue(current, option))
                  }
                  className={`rounded-full border px-tc-3 py-tc-1 text-tc-caption ${
                    uploadSubjects.includes(option)
                      ? 'border-tc-primary text-tc-primary'
                      : 'border-tc-border text-tc-muted'
                  }`}
                  aria-pressed={uploadSubjects.includes(option)}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-tc-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setUploadModalOpen(false)
                setUploadFile(null)
              }}
            >
              Cancel
            </Button>
            <Button type="button" onClick={confirmUpload}>
              {actionVerb('upload', 'idle')}
            </Button>
          </div>
        </div>
      </Dialog>
      {uploadNotice && (
        <Toast
          title={uploadNotice.title}
          message={uploadNotice.message}
          type={uploadNotice.type}
          onDismiss={() => setUploadNotice(null)}
        />
      )}
    </div>
  )
}

function MetadataDialog({
  qnr,
  workspaceId,
  onClose,
  onSaved,
}: {
  qnr: Qnr
  workspaceId: number
  onClose: () => void
  onSaved: (id: number, frameworks: string[], subjectAreas: string[]) => void
}) {
  const [frameworks, setFrameworks] = useState(() =>
    normalizeLabels(qnr.frameworks)
  )
  const [subjects, setSubjects] = useState(() =>
    normalizeLabels(qnr.subject_areas)
  )
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const response = await fetch(
        `/api/questionnaires/${qnr.id}/metadata?workspace_id=${workspaceId}`,
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            frameworks,
            subject_areas: subjects,
          }),
        }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || !acknowledged(data)) {
        setError(
          mutationFailureNotice(
            response.status,
            data,
            'The metadata was not saved. Try again.'
          ).message
        )
        return
      }
      onSaved(qnr.id, frameworks, subjects)
      setSaved(true)
    } catch {
      setError('The metadata was not saved. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit metadata · ${qnr.display_id}`}
      closeDisabled={saving}
    >
      <div className="space-y-tc-4">
        <div>
          <p className="mb-tc-2 text-tc-label text-tc-muted">Frameworks</p>
          <div className="flex flex-wrap gap-tc-2">
            {FRAMEWORK_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={frameworks.includes(option)}
                onClick={() =>
                  setFrameworks((current) => toggleValue(current, option))
                }
                className={`rounded-tc-xs border px-tc-2 py-tc-1 text-tc-label text-tc-text ${
                  frameworks.includes(option)
                    ? 'border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)]'
                    : 'border-tc-border bg-tc-surface-sunken'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-tc-2 text-tc-label text-tc-muted">Subject areas</p>
          <div className="flex flex-wrap gap-tc-2">
            {SUBJECT_AREA_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={subjects.includes(option)}
                onClick={() =>
                  setSubjects((current) => toggleValue(current, option))
                }
                className={`rounded-tc-xs border px-tc-2 py-tc-1 text-tc-label text-tc-text ${
                  subjects.includes(option)
                    ? 'border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)]'
                    : 'border-tc-border bg-tc-surface-sunken'
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        {error && (
          <p role="alert" className="text-tc-label text-tc-danger">
            {error}
          </p>
        )}
        {saved && (
          <p role="status" className="text-tc-label text-tc-text">
            Metadata saved.
          </p>
        )}
        <div className="flex justify-end gap-tc-2">
          <Button
            type="button"
            size="sm"
            onClick={() => void save()}
            disabled={saving}
          >
            {saving ? 'Saving' : 'Save metadata'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
