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
  DocumentListSkeleton,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
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
import {
  failureOf,
  isAbortError,
  listFromPayload,
  readSectionJson,
} from '@/lib/section-load'
import {
  FRAMEWORK_OPTIONS,
  SUBJECT_AREA_OPTIONS,
  normalizeLabels,
} from '@/lib/listMetadata'
import { dialogAttributes } from '@/lib/dialog'
import { jobsHref, parseJobHistory } from '@/lib/job-history-consumer'

type Doc = {
  id: number
  display_id: string
  filename: string
  file_type?: string | null
  status: string
  index_error?: string | null
  created_at: string | null
  deleted_at?: string | null
  frameworks?: string[]
  subject_areas?: string[]
  source_eligibility?: string | null
  eligibility?: string | null
  freshness?: string | null
  version?: string | null
  content_version?: string | null
  source_preview_url?: string | null
  index_job_id?: number | null
  index_job_status?: string | null
}

type IndexJob = { id: number; status: string }
type IndexPhase = 'queued' | 'indexed' | 'failed'
type ActiveDialog =
  | { kind: 'archive'; doc: Doc }
  | { kind: 'delete'; doc: Doc }
  | { kind: 'restore'; doc: Doc }
  | { kind: 'bulk' }

/** Extensions accepted by FileService.ALLOWED_RAW_EXTENSIONS. */
const ACCEPT_ATTRIBUTE = '.pdf,.docx,.doc,.xlsx,.xls,.txt'
const FORMAT_LINE = 'Accepted formats: PDF, DOCX, DOC, XLSX, XLS, and TXT.'
const PAGE_SIZE = 25
const DEFAULT_SORT = 'created_at:desc'
const LIST_CONTRACT =
  'The document list requests one page from the server. The server sorts that page and returns the total. This page sends page, page size, sort, and order.'
const SELECTION_SCOPE =
  'Selection applies to every document on this page for the current workspace. Changing the workspace, a filter, or the page clears it.'
const REINDEX_NOTE =
  'Reindex retries the index job on the row. An administrator can retry that job when it failed or was cancelled. There is no separate reindex route.'
const DELETE_NOTE =
  'Permanent deletion is not available. The document API archives a document and does not erase one document.'
const SEARCH_DEBOUNCE_MS = 300
const FIELD_CLASS =
  'w-full min-w-0 rounded-tc-xs border border-tc-border-strong bg-tc-surface-overlay px-tc-2 py-tc-2 text-tc-label text-tc-text'
const LABEL_CLASS = 'mb-tc-1 block text-tc-label font-medium text-tc-muted'

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

function isoFromLocal(value: string): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

function sortParams(sortKey: string): { sort: string; order: string } {
  const [sort, order] = sortKey.split(':')
  if (
    (sort === 'created_at' || sort === 'filename' || sort === 'status') &&
    (order === 'asc' || order === 'desc')
  ) {
    return { sort, order }
  }
  return { sort: 'created_at', order: 'desc' }
}

function sizeLine(bytes: number | null): string {
  if (bytes == null) return 'Size limit: not reported.'
  const mebibyte = 1024 * 1024
  if (bytes % mebibyte === 0) return `Size limit: ${bytes / mebibyte} MB.`
  return `Size limit: ${bytes} bytes.`
}

function readTotal(data: unknown, rowCount: number): number {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return rowCount
  const value = (data as { total?: unknown }).total
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
    ? value
    : rowCount
}

function readUploadLimit(data: unknown): number | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const value = (data as { max_upload_bytes?: unknown }).max_upload_bytes
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : null
}

function rowIndexJob(row: Doc): IndexJob | null {
  const id = row.index_job_id
  const status = row.index_job_status
  if (
    typeof id === 'number' &&
    Number.isInteger(id) &&
    id > 0 &&
    typeof status === 'string' &&
    status.trim()
  ) {
    return { id, status }
  }
  return null
}

function listUrl(input: {
  workspaceId: number
  search: string
  framework: string
  subjectArea: string
  status: string
  createdFrom: string
  createdTo: string
  archivedMode: string
  page: number
  sortKey: string
}): string {
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
  const { sort, order } = sortParams(input.sortKey)
  params.set('page', String(input.page))
  params.set('page_size', String(PAGE_SIZE))
  params.set('sort', sort)
  params.set('order', order)
  return `/api/documents/?${params.toString()}`
}

function reported(row: Doc, keys: Array<keyof Doc>): string | null {
  const record = row as unknown as Record<string, unknown>
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

function previewPath(value: string | null | undefined): string | null {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return null
  if (value.includes('://') || value.includes('\\')) return null
  return value
}

function statusLabel(status: string): string {
  if (status === 'failed') return 'Indexing failed'
  if (status === 'indexed') return 'Indexed'
  if (status === 'indexing') return 'Indexing'
  if (status === 'uploaded') return 'Uploaded'
  return status
}

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value]
}

export default function DocumentsPage() {
  const { workspace, permissions, loading: authLoading } = useAuth()
  const workspaceId = workspace?.id
  const canEdit = permissions.can_edit
  const canAdmin = permissions.can_admin
  const [docs, setDocs] = useState<Doc[]>([])
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
  const [listPage, setListPage] = useState(1)
  const [sortKey, setSortKey] = useState(DEFAULT_SORT)
  const [listTotal, setListTotal] = useState(0)
  const [maxUploadBytes, setMaxUploadBytes] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [indexJobs, setIndexJobs] = useState<Map<number, IndexJob>>(new Map())
  const [indexProgress, setIndexProgress] = useState<IndexPhase | null>(null)
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
  const [metadataDoc, setMetadataDoc] = useState<Doc | null>(null)
  const [preview, setPreview] = useState<{
    docId: number
    deps: Record<string, number | string>
  } | null>(null)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [retryingId, setRetryingId] = useState<number | null>(null)
  const [retryNotice, setRetryNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const generation = useRef(0)
  const indexPoll = useRef<AbortController | null>(null)
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
    sortKey,
    listPage,
    loadAttempt,
  ].join('\n')
  const [seenLoadKey, setSeenLoadKey] = useState<string | null>(null)
  if (!authLoading && seenLoadKey !== loadKey) {
    setSeenLoadKey(loadKey)
    const flags = listLoadFlags({
      enabled: workspaceId != null,
      hasRows: docs.length > 0,
    })
    if (flags.loading !== null) setLoading(flags.loading)
    setRefreshing(flags.refreshing)
    if (flags.clearFailure) setLoadFailure(null)
  }

  const listQueryKey = [
    workspaceId ?? '',
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    sortKey,
  ].join('\n')
  const [seenListQuery, setSeenListQuery] = useState<string | null>(null)
  if (seenListQuery !== listQueryKey) {
    setSeenListQuery(listQueryKey)
    if (seenListQuery !== null && listPage !== 1) setListPage(1)
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
    sortKey,
    listPage,
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
      setIndexJobs(new Map())
      setIndexProgress(null)
      setRetryNotice(null)
    }
  }

  const filters = {
    workspaceId: workspaceId ?? 0,
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    page: listPage,
    sortKey,
  }

  const loadJobs = useCallback(
    async (signal: AbortSignal, gen: number, rows: Doc[]) => {
      if (workspaceId == null || rows.length === 0) {
        if (gen === generation.current) setIndexJobs(new Map())
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
        const next = new Map<number, IndexJob>()
        for (const job of history.items) {
          if (
            job.kind !== 'index_document' ||
            job.objectRef?.type !== 'document' ||
            !job.status
          ) {
            continue
          }
          if (!next.has(job.objectRef.id)) {
            next.set(job.objectRef.id, { id: job.id, status: job.status })
          }
        }
        setIndexJobs(next)
      } catch (error) {
        if (isAbortError(error) || signal.aborted) return
        if (gen === generation.current) setIndexJobs(new Map())
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
      page: listPage,
      sortKey,
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
        const rows = listFromPayload<Doc>(data, ['items', 'documents'])
        if (controller.signal.aborted || gen !== generation.current) return
        setDocs(rows)
        setListTotal(readTotal(data, rows.length))
        setMaxUploadBytes(readUploadLimit(data))
        setLoadFailure(null)
        void loadJobs(controller.signal, gen, rows)
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) return
        if (gen !== generation.current) return
        setDocs([])
        setListTotal(0)
        setMaxUploadBytes(null)
        setIndexJobs(new Map())
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
    sortKey,
    listPage,
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
      indexPoll.current?.abort()
    }
  }, [workspaceId])

  const activeDocs = docs.filter((row) => !row.deleted_at)
  const selectAll =
    activeDocs.length > 0 && activeDocs.every((row) => selectedIds.has(row.id))
  const selectSome = activeDocs.some((row) => selectedIds.has(row.id))
  useEffect(() => {
    const element = selectAllRef.current
    if (element) element.indeterminate = selectSome && !selectAll
  }, [selectSome, selectAll])

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

  const clearFilters = () => {
    clearSearch()
    setFramework('')
    setSubjectArea('')
    setStatus('')
    setCreatedFrom('')
    setCreatedTo('')
    setArchivedMode('active')
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

  const watchIndex = async (jobId: number, docId: number) => {
    if (workspaceId == null) return
    indexPoll.current?.abort()
    const controller = new AbortController()
    indexPoll.current = controller
    const url = listUrl({ ...filters, workspaceId })
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
        const jobStatus = readStatus(await response.json().catch(() => null))
        if (jobStatus === 'queued' || jobStatus === 'running') {
          setIndexProgress('queued')
          await delay(1000, controller.signal)
          continue
        }
        if (jobStatus === 'failed' || jobStatus === 'cancelled') {
          setIndexProgress('failed')
          return
        }
        if (jobStatus === 'completed') {
          const listed = await fetch(url, {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          })
          const listedData = await readSectionJson(listed)
          const rows = listFromPayload<Doc>(listedData, ['items', 'documents'])
          if (controller.signal.aborted) return
          setDocs(rows)
          setListTotal(readTotal(listedData, rows.length))
          setMaxUploadBytes(readUploadLimit(listedData))
          const row = rows.find((item) => item.id === docId)
          if (row?.status === 'indexed') setIndexProgress('indexed')
          else if (row?.status === 'failed') setIndexProgress('failed')
          else setIndexProgress('queued')
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
    setUploading(true)
    setUploadModalOpen(false)
    setUploadNotice(null)
    setIndexProgress(null)
    const body = new FormData()
    body.append('workspace_id', String(workspaceId))
    body.append('file', file)
    if (uploadFrameworks.length > 0) {
      body.append('frameworks', uploadFrameworks.join(','))
    }
    if (uploadSubjects.length > 0) {
      body.append('subject_areas', uploadSubjects.join(','))
    }
    void fetch('/api/documents/upload', {
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
        const docId = readPositiveInt(data, 'id')
        if (jobId && docId) void watchIndex(jobId, docId)
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

  const openArchive = (doc: Doc) => {
    if (workspaceId == null) return
    const docId = doc.id
    setMetadataDoc(null)
    setDialog({ kind: 'archive', doc })
    setPreview(null)
    setOutcome(null)
    setDialogError(null)
    void fetch(
      `/api/documents/${docId}/delete-preview?workspace_id=${workspaceId}`,
      { credentials: 'include' }
    )
      .then(async (response) => (response.ok ? response.json() : null))
      .then((data: unknown) => {
        if (!data || typeof data !== 'object') return
        const dependencies = (data as { dependencies?: unknown }).dependencies
        if (dependencies && typeof dependencies === 'object') {
          setPreview({
            docId,
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
        `/api/documents/${dialog.doc.id}?workspace_id=${workspaceId}`,
        { method: 'DELETE', credentials: 'include' }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || !acknowledged(data)) {
        setDialogError(
          mutationFailureNotice(
            response.status,
            data,
            'The document was not archived. Try again.'
          ).message
        )
        return
      }
      setOutcome('Archived.')
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The document was not archived. Try again.')
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
        `/api/documents/${dialog.doc.id}/restore?workspace_id=${workspaceId}`,
        { method: 'POST', credentials: 'include' }
      )
      const data = await response.json().catch(() => null)
      if (!response.ok || !acknowledged(data)) {
        setDialogError(
          mutationFailureNotice(
            response.status,
            data,
            'The document was not restored. Try again.'
          ).message
        )
        return
      }
      setOutcome('Restored.')
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The document was not restored. Try again.')
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
        `/api/documents/bulk-delete?workspace_id=${workspaceId}`,
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
            'The documents were not archived. Try again.'
          ).message
        )
        return
      }
      setOutcome('Archived.')
      setSelectedIds(new Set())
      setLoadAttempt((value) => value + 1)
    } catch {
      setDialogError('The documents were not archived. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const retryIndex = async (doc: Doc, job: IndexJob) => {
    if (workspaceId == null) return
    setRetryingId(doc.id)
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
            'Indexing was not queued. Try again.'
          ).message
        )
        return
      }
      setRetryNotice(`Indexing queued for ${doc.display_id}`)
    } catch {
      setActionError('Indexing was not queued. Try again.')
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
  const archiveDoc = dialog?.kind === 'archive' ? dialog.doc : null
  const shownDeps =
    preview && archiveDoc && preview.docId === archiveDoc.id ? preview.deps : {}
  const deleteDoc = dialog?.kind === 'delete' ? dialog.doc : null
  const restoreDoc = dialog?.kind === 'restore' ? dialog.doc : null

  return (
    <div className="min-w-0 max-w-full overflow-x-hidden p-tc-4 sm:p-tc-7">
      <div className="mb-tc-4 flex min-w-0 items-center gap-tc-3">
        <h1 className="text-tc-headline font-semibold text-tc-text">
          Documents
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
        <p className="mb-tc-4 max-w-3xl text-tc-label text-tc-muted">
          {REINDEX_NOTE}
        </p>
      )}
      {canEdit && (
        <Card className="mb-tc-4">
          <p
            id="doc-upload-constraints"
            className="mb-tc-3 text-tc-label text-tc-muted"
          >
            {FORMAT_LINE} {sizeLine(maxUploadBytes)}
          </p>
          <input
            id="doc-upload"
            type="file"
            className="hidden"
            accept={ACCEPT_ATTRIBUTE}
            aria-describedby="doc-upload-constraints"
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
            aria-describedby="doc-upload-constraints"
            data-upload-state={uploading ? 'pending' : 'idle'}
            onClick={() => document.getElementById('doc-upload')?.click()}
          >
            {uploading
              ? actionVerb('upload', 'pending')
              : actionVerb('upload', 'idle')}
          </Button>
          {indexProgress && (
            <p
              role="status"
              data-index-progress={indexProgress}
              className="mt-tc-3 text-tc-label text-tc-text"
            >
              {indexProgress === 'queued'
                ? 'Queued'
                : indexProgress === 'indexed'
                  ? 'Indexed'
                  : 'Failed'}
            </p>
          )}
        </Card>
      )}
      {workspaceId != null && (
        <Card className="mb-tc-4">
          <div className="grid grid-cols-1 gap-tc-3 md:grid-cols-2 xl:grid-cols-3">
            <Input
              id="doc-search"
              label="Search documents"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="ID, filename, framework, subject, or status"
            />
            <div className="min-w-0">
              <label htmlFor="doc-framework" className={LABEL_CLASS}>
                Framework
              </label>
              <select
                id="doc-framework"
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
              <label htmlFor="doc-subject" className={LABEL_CLASS}>
                Subject area
              </label>
              <select
                id="doc-subject"
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
              <label htmlFor="doc-created-from" className={LABEL_CLASS}>
                Created from
              </label>
              <input
                id="doc-created-from"
                type="datetime-local"
                className={FIELD_CLASS}
                value={createdFrom}
                onChange={(event) => setCreatedFrom(event.target.value)}
              />
            </div>
            <div className="min-w-0">
              <label htmlFor="doc-created-to" className={LABEL_CLASS}>
                Created to
              </label>
              <input
                id="doc-created-to"
                type="datetime-local"
                className={FIELD_CLASS}
                value={createdTo}
                onChange={(event) => setCreatedTo(event.target.value)}
              />
            </div>
            <div className="min-w-0">
              <label htmlFor="doc-status" className={LABEL_CLASS}>
                Document status
              </label>
              <select
                id="doc-status"
                className={FIELD_CLASS}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="">All statuses</option>
                {['uploaded', 'indexing', 'indexed', 'failed'].map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="min-w-0">
              <label htmlFor="doc-archived" className={LABEL_CLASS}>
                Archive filter
              </label>
              <select
                id="doc-archived"
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
              <label htmlFor="doc-sort" className={LABEL_CLASS}>
                Sort
              </label>
              <select
                id="doc-sort"
                className={FIELD_CLASS}
                value={sortKey}
                onChange={(event) => setSortKey(event.target.value)}
              >
                <option value="created_at:desc">Newest first</option>
                <option value="created_at:asc">Oldest first</option>
                <option value="filename:asc">Filename A to Z</option>
                <option value="filename:desc">Filename Z to A</option>
                <option value="status:asc">Status</option>
              </select>
            </div>
          </div>
          {chips.length > 0 && (
            <ul
              aria-label="Selected filters"
              className="mt-tc-3 flex flex-wrap gap-tc-2"
            >
              {chips.map((chip) => (
                <li key={chip.id}>
                  <button
                    type="button"
                    aria-label={`Remove ${chip.removeName} filter`}
                    onClick={chip.onRemove}
                    className="inline-flex min-h-11 items-center rounded-full border border-tc-border bg-tc-surface-raised px-tc-3 text-tc-label text-tc-text"
                  >
                    {chip.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      <Card>
        {actionError && (
          <p role="alert" className="mb-tc-3 text-tc-label text-tc-danger">
            {actionError}
          </p>
        )}
        {retryNotice && (
          <p role="status" className="mb-tc-3 text-tc-label text-tc-text">
            {retryNotice}
          </p>
        )}
        {authLoading || (workspaceId != null && loading) ? (
          <LoadingState
            label="Loading documents"
            resetKey={loadAttempt}
            onRetry={() => setLoadAttempt((value) => value + 1)}
          >
            <DocumentListSkeleton />
          </LoadingState>
        ) : workspaceId == null ? (
          <EmptyState
            title="No workspace is selected"
            description="Choose a workspace to see its documents."
          />
        ) : loadFailure ? (
          <ErrorState
            failure={loadFailure}
            onRetry={() => setLoadAttempt((value) => value + 1)}
          />
        ) : docs.length === 0 ? (
          narrowed ? (
            <EmptyState
              title="No matching documents"
              description="No documents match the current search or filters."
              action={
                <Button type="button" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              title="No documents yet"
              description={
                canEdit
                  ? 'Upload PDF, DOCX, DOC, XLSX, XLS, or TXT files to use as evidence.'
                  : 'Ask an editor to upload evidence documents.'
              }
              action={
                canEdit && (
                  <Button
                    type="button"
                    onClick={() =>
                      document.getElementById('doc-upload')?.click()
                    }
                  >
                    Upload your first document
                  </Button>
                )
              }
            />
          )
        ) : (
          <div aria-busy={refreshing ? true : undefined}>
            {canEdit && selectedCount > 0 && (
              <div
                role="status"
                className="mb-tc-3 flex flex-wrap items-center justify-between gap-tc-2 rounded-tc border border-tc-border bg-tc-surface-raised px-tc-3 py-tc-2"
              >
                <span className="text-tc-label text-tc-text">
                  {selectedCount}{' '}
                  {selectedCount === 1 ? 'document' : 'documents'} selected in
                  this result
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
            {canEdit && activeDocs.length > 0 && (
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
                          : new Set(activeDocs.map((row) => row.id))
                      )
                    }}
                    aria-label="Select all documents on this page"
                    className="h-4 w-4 rounded border-tc-border"
                  />
                  Select all documents on this page
                </label>
              </div>
            )}
            <ul
              aria-label="Documents"
              className="min-w-0 divide-y divide-tc-border"
            >
              {docs.map((row) => {
                const job = rowIndexJob(row) ?? indexJobs.get(row.id) ?? null
                const canRetry =
                  canAdmin &&
                  job !== null &&
                  (job.status === 'failed' || job.status === 'cancelled') &&
                  !row.deleted_at
                const source = previewPath(row.source_preview_url)
                const actions: RowAction[] = [
                  {
                    id: 'copy_id',
                    label: 'Copy ID',
                    onClick: () => {
                      void navigator.clipboard?.writeText(row.display_id)
                    },
                  },
                  {
                    id: 'edit_metadata',
                    label: 'Edit metadata',
                    onClick: () => {
                      setDialog(null)
                      setMetadataDoc(row)
                    },
                  },
                ]
                if (row.deleted_at) {
                  actions.push({
                    id: 'restore',
                    label: 'Restore',
                    onClick: () => {
                      setMetadataDoc(null)
                      setOutcome(null)
                      setDialogError(null)
                      setDialog({ kind: 'restore', doc: row })
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
                        setMetadataDoc(null)
                        setOutcome(null)
                        setDialogError(null)
                        setDialog({ kind: 'delete', doc: row })
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
                        <span className="min-w-0 break-all font-medium text-tc-text">
                          {row.filename}
                        </span>
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
                        <span className="text-tc-caption uppercase text-tc-muted">
                          {row.file_type || 'file'}
                        </span>
                      </div>
                      <CategoryChipsRow
                        frameworks={normalizeLabels(row.frameworks)}
                        subjectAreas={normalizeLabels(row.subject_areas)}
                      />
                      <p className="break-words text-tc-label text-tc-text">
                        Source eligibility:{' '}
                        {reported(row, ['source_eligibility', 'eligibility']) ??
                          'Not reported'}
                      </p>
                      <p className="break-words text-tc-label text-tc-text">
                        Freshness:{' '}
                        {reported(row, ['freshness']) ?? 'Not reported'}
                      </p>
                      <p className="break-words text-tc-label text-tc-text">
                        Version:{' '}
                        {reported(row, ['version', 'content_version']) ??
                          'Not reported'}
                      </p>
                      {source ? (
                        <Link
                          href={source}
                          className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
                        >
                          View source
                        </Link>
                      ) : (
                        <p className="text-tc-label text-tc-muted">
                          Source preview is not available.
                        </p>
                      )}
                      {job && workspaceId != null && (
                        <Link
                          href={jobsHref(workspaceId)}
                          className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
                        >
                          View index job {job.id}
                        </Link>
                      )}
                      {row.status === 'failed' && row.index_error && (
                        <p className="break-words text-tc-label text-tc-muted">
                          {row.index_error}
                        </p>
                      )}
                      {canRetry && job && (
                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          disabled={retryingId === row.id}
                          aria-busy={retryingId === row.id}
                          onClick={() => void retryIndex(row, job)}
                        >
                          {retryingId === row.id
                            ? 'Retrying'
                            : `Retry indexing for ${row.display_id}`}
                        </Button>
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
          </div>
        )}
        {workspaceId != null &&
          !authLoading &&
          !loading &&
          !loadFailure &&
          listTotal > PAGE_SIZE && (
            <div className="mt-tc-3 flex flex-wrap items-center gap-tc-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={listPage <= 1}
                aria-label="Previous page"
                onClick={() =>
                  setListPage((current) => Math.max(1, current - 1))
                }
              >
                Previous
              </Button>
              <span className="text-tc-label text-tc-muted">
                Page {listPage} of {Math.ceil(listTotal / PAGE_SIZE)}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={listPage >= Math.ceil(listTotal / PAGE_SIZE)}
                aria-label="Next page"
                onClick={() => setListPage((current) => current + 1)}
              >
                Next
              </Button>
            </div>
          )}
      </Card>
      <Dialog
        open={Boolean(archiveDoc)}
        onClose={closeDialog}
        title="Archive document?"
        description="Archiving hides this document from the active list. It can be restored. This is not permanent deletion."
        role="alertdialog"
        closeDisabled={busy}
      >
        {archiveDoc && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {archiveDoc.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {archiveDoc.display_id}
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
        open={Boolean(deleteDoc)}
        onClose={closeDialog}
        title="Delete record?"
        description={DELETE_NOTE}
        role="alertdialog"
      >
        {deleteDoc && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {deleteDoc.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {deleteDoc.display_id}
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
        open={Boolean(restoreDoc)}
        onClose={closeDialog}
        title="Restore document?"
        description="Restoring returns this archived document to the active list after the server accepts it."
        role="alertdialog"
        closeDisabled={busy}
      >
        {restoreDoc && (
          <div className="space-y-tc-3">
            <p className="break-all font-medium text-tc-text">
              {restoreDoc.filename}
            </p>
            <p className="text-tc-label text-tc-muted">
              ID: {restoreDoc.display_id}
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
        title="Archive selected documents?"
        description="Archiving hides the selected documents from the active list. They can be restored. This is not permanent deletion."
        role="alertdialog"
        closeDisabled={busy}
      >
        <div className="space-y-tc-3">
          <p className="break-words text-tc-label text-tc-muted">
            {docs
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
      {metadataDoc && workspaceId != null && (
        <MetadataDialog
          doc={metadataDoc}
          workspaceId={workspaceId}
          onClose={() => setMetadataDoc(null)}
          onSaved={(id, frameworks, subjectAreas) => {
            setDocs((current) =>
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
            setMetadataDoc((current) =>
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
        title="Upload Evidence Document"
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
  doc,
  workspaceId,
  onClose,
  onSaved,
}: {
  doc: Doc
  workspaceId: number
  onClose: () => void
  onSaved: (id: number, frameworks: string[], subjectAreas: string[]) => void
}) {
  const [frameworks, setFrameworks] = useState(() =>
    normalizeLabels(doc.frameworks)
  )
  const [subjects, setSubjects] = useState(() =>
    normalizeLabels(doc.subject_areas)
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
        `/api/documents/${doc.id}/metadata?workspace_id=${workspaceId}`,
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
      onSaved(doc.id, frameworks, subjects)
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
      title={`Edit metadata · ${doc.display_id}`}
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
