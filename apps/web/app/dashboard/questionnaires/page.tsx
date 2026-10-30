'use client'

import { useEffect, useState, useRef } from 'react'
import Link from 'next/link'
import {
  Card,
  Button,
  Modal,
  QuestionnaireListSkeleton,
  EmptyState,
  ErrorState,
  LoadingState,
  DisplayIdText,
  CreatedTimestampText,
  CategoryChipsRow,
  DeleteConfirmationModal,
  BulkSelectionBar,
  BulkDeleteConfirmationModal,
  MetadataEditorModal,
  RegistryRowActionsMenu,
  Toast,
  ToastViewport,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  mutationFailureNotice,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import {
  failureOf,
  isAbortError,
  listFromPayload,
  readSectionJson,
} from '@/lib/section-load'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'
import { listLoadFlags } from '@/lib/render-state'
import {
  FRAMEWORK_OPTIONS,
  SUBJECT_AREA_OPTIONS,
  normalizeLabels,
} from '@/lib/listMetadata'
import { actionVerb, confirmedActionNotice } from '@/lib/action-copy'

export default function QuestionnairesPage() {
  const { user, workspace } = useAuth()
  return <QuestionnairesRegistry key={`${user?.id}:${workspace?.id}`} />
}

function QuestionnairesRegistry() {
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canUpload = permissions.can_edit
  const [qnrs, setQnrs] = useState<
    {
      id: number
      display_id: string
      filename: string
      status: string
      created_at: string | null
      deleted_at?: string | null
      frameworks?: string[]
      subject_areas?: string[]
    }[]
  >([])
  const [loading, setLoading] = useState(true)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadNotice, setUploadNotice] = useState<{
    title: string
    message: string
    type: 'success' | 'error'
  } | null>(null)
  const [search, setSearch] = useState('')
  const [framework, setFramework] = useState('')
  const [subjectArea, setSubjectArea] = useState('')
  const [status, setStatus] = useState('')
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')
  const [archivedMode, setArchivedMode] = useState<
    'active' | 'include' | 'only'
  >('active')
  const [deleteQnr, setDeleteQnr] = useState<{
    id: number
    display_id: string
    filename: string
  } | null>(null)
  const [deleteDeps, setDeleteDeps] = useState<Record<string, number | string>>(
    {}
  )
  const [deleteUnmodeledWarning, setDeleteUnmodeledWarning] = useState<
    string | null
  >(null)
  const [deleting, setDeleting] = useState(false)
  const [editQnr, setEditQnr] = useState<{
    id: number
    display_id: string
    frameworks?: string[]
    subject_areas?: string[]
  } | null>(null)
  const [savingMetadata, setSavingMetadata] = useState(false)
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const [restoringIds, setRestoringIds] = useState<Set<number>>(new Set())
  const [restoreErrors, setRestoreErrors] = useState<Record<number, string>>({})
  const [mutationMessage, setMutationMessage] = useState<string | null>(null)
  const metadataBusy = useRef(false)
  const restoreBusy = useRef(new Set<number>())
  const rowActions = useRef(new Map<number, HTMLFieldSetElement>())
  const mutationGeneration = useRef(0)
  useEffect(() => {
    mutationGeneration.current += 1
    return () => {
      mutationGeneration.current += 1
    }
  }, [])
  const focusActions = (id: number) => {
    requestAnimationFrame(() =>
      rowActions.current.get(id)?.querySelector('button')?.focus()
    )
  }
  const closeMetadata = () => {
    if (metadataBusy.current) return
    if (editQnr) focusActions(editQnr.id)
    setEditQnr(null)
    setMetadataError(null)
  }
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploadFrameworks, setUploadFrameworks] = useState<string[]>([])
  const [uploadSubjects, setUploadSubjects] = useState<string[]>([])

  const activeQnrs = (Array.isArray(qnrs) ? qnrs : []).filter(
    (q) => !q.deleted_at
  )
  const selectAll =
    activeQnrs.length > 0 && activeQnrs.every((q) => selectedIds.has(q.id))
  const selectSome = activeQnrs.some((q) => selectedIds.has(q.id))
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const toggleSelectAll = () => {
    if (selectAll) setSelectedIds(new Set())
    else setSelectedIds(new Set(activeQnrs.map((q) => q.id)))
  }
  const selectAllRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const el = selectAllRef.current
    if (el)
      (el as HTMLInputElement & { indeterminate?: boolean }).indeterminate =
        selectSome && !selectAll
  }, [selectSome, selectAll])

  const qnrKey = [
    workspaceId ?? '',
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    loadAttempt,
  ].join('\n')
  const qnrGen = useKeyedGeneration(qnrKey)
  if (qnrGen.changed) {
    const flags = listLoadFlags({
      enabled: workspaceId != null,
      hasRows: qnrs.length > 0,
    })
    if (flags.loading !== null) setLoading(flags.loading)
    if (flags.refreshing) setRefreshing(true)
    if (flags.clearFailure) setLoadFailure(null)
  }

  useEffect(() => {
    if (workspaceId == null) return
    const params = new URLSearchParams({ workspace_id: String(workspaceId) })
    if (search.trim()) params.set('search', search.trim())
    if (framework) params.set('framework', framework)
    if (subjectArea) params.set('subject_area', subjectArea)
    if (status) params.set('status', status)
    if (createdFrom)
      params.set('created_from', new Date(createdFrom).toISOString())
    if (createdTo) params.set('created_to', new Date(createdTo).toISOString())
    params.set('archived', archivedMode)
    fetch(`/api/questionnaires/?${params.toString()}`, {
      credentials: 'include',
    })
      .then(async (res) => {
        const data = await readSectionJson(res)
        return listFromPayload<(typeof qnrs)[number]>(data, [
          'items',
          'questionnaires',
        ])
      })
      .then((rows) => {
        setQnrs(rows)
        setLoadFailure(null)
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        setQnrs([])
        setLoadFailure(failureOf(error))
      })
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }, [
    workspaceId,
    search,
    framework,
    subjectArea,
    status,
    createdFrom,
    createdTo,
    archivedMode,
    loadAttempt,
  ])

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setUploadFile(file)
    setUploadFrameworks([])
    setUploadSubjects([])
    setUploadModalOpen(true)
  }

  const toggleUploadFw = (fw: string) => {
    setUploadFrameworks((prev) =>
      prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw]
    )
  }

  const confirmUpload = () => {
    if (!uploadFile || workspaceId == null) return
    setUploading(true)
    setUploadModalOpen(false)
    setError(null)
    setUploadNotice(null)
    const fd = new FormData()
    fd.append('workspace_id', String(workspaceId))
    fd.append('file', uploadFile)
    if (uploadFrameworks.length > 0)
      fd.append('frameworks', uploadFrameworks.join(','))
    if (uploadSubjects.length > 0)
      fd.append('subject_areas', uploadSubjects.join(','))
    fetch('/api/questionnaires/upload', {
      method: 'POST',
      credentials: 'include',
      body: fd,
    })
      .then(async (r) => {
        const data = await r.json().catch(() => null)
        if (!r.ok) {
          const notice = mutationFailureNotice(
            r.status,
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
        if (workspaceId == null) return
        const params = new URLSearchParams({
          workspace_id: String(workspaceId),
        })
        fetch(`/api/questionnaires/?${params.toString()}`, {
          credentials: 'include',
        })
          .then(async (r) => {
            const data = await readSectionJson(r)
            return listFromPayload<(typeof qnrs)[number]>(data, [
              'items',
              'questionnaires',
            ])
          })
          .then((rows) => {
            setQnrs(rows)
            setLoadFailure(null)
          })
          .catch((error: unknown) => {
            if (isAbortError(error)) return
            setQnrs([])
            setLoadFailure(failureOf(error))
          })
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

  const confirmDelete = async () => {
    if (!workspaceId || !deleteQnr) return
    setDeleting(true)
    try {
      const r = await fetch(
        `/api/questionnaires/${deleteQnr.id}?workspace_id=${workspaceId}`,
        {
          method: 'DELETE',
          credentials: 'include',
        }
      )
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setError((data?.detail as string) || 'Delete failed')
      } else {
        setDeleteDeps(data?.dependencies || {})
        setDeleteQnr(null)
        setQnrs((prev) => prev.filter((q) => q.id !== deleteQnr.id))
      }
    } catch {
      setError('Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  const confirmBulkDelete = async () => {
    if (!workspaceId || selectedIds.size === 0) return
    setBulkDeleting(true)
    try {
      const r = await fetch(
        `/api/questionnaires/bulk-delete?workspace_id=${workspaceId}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: Array.from(selectedIds) }),
        }
      )
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setError((data?.detail as string) || 'Bulk delete failed')
      } else {
        setSelectedIds(new Set())
        setBulkDeleteOpen(false)
        const params = new URLSearchParams({
          workspace_id: String(workspaceId),
        })
        if (search.trim()) params.set('search', search.trim())
        if (framework) params.set('framework', framework)
        if (subjectArea) params.set('subject_area', subjectArea)
        if (status) params.set('status', status)
        if (createdFrom)
          params.set('created_from', new Date(createdFrom).toISOString())
        if (createdTo)
          params.set('created_to', new Date(createdTo).toISOString())
        params.set('archived', archivedMode)
        const res = await fetch(`/api/questionnaires/?${params.toString()}`, {
          credentials: 'include',
        })
        const json = await res.json().catch(() => ({}))
        setQnrs(
          Array.isArray(json)
            ? json
            : Array.isArray(json?.items)
              ? json.items
              : Array.isArray(json?.questionnaires)
                ? json.questionnaires
                : []
        )
      }
    } catch {
      setError('Bulk delete failed')
    } finally {
      setBulkDeleting(false)
    }
  }

  const openDelete = async (q: {
    id: number
    display_id: string
    filename: string
  }) => {
    setDeleteQnr(q)
    setDeleteUnmodeledWarning(null)
    if (!workspaceId) return
    const r = await fetch(
      `/api/questionnaires/${q.id}/delete-preview?workspace_id=${workspaceId}`,
      { credentials: 'include' }
    )
    const data = await r.json().catch(() => ({}))
    setDeleteDeps(data?.dependencies || {})
    setDeleteUnmodeledWarning(data?.unmodeled_warning || null)
  }

  const requireAcknowledgement = async (response: Response, id?: number) => {
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      const notice = mutationFailureNotice(response.status, data, 'Try again.')
      throw new Error(`${notice.title}: ${notice.message}`)
    }
    if (!data || data.ok !== true || (id !== undefined && data.id !== id)) {
      throw new Error('The response could not be confirmed. Try again.')
    }
  }

  const restoreQnr = async (id: number) => {
    if (!workspaceId || restoreBusy.current.has(id)) return
    restoreBusy.current.add(id)
    setRestoringIds(new Set(restoreBusy.current))
    setRestoreErrors((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setMutationMessage(null)
    const generation = mutationGeneration.current
    try {
      const response = await fetch(
        `/api/questionnaires/${id}/restore?workspace_id=${workspaceId}`,
        { method: 'POST', credentials: 'include' }
      )
      await requireAcknowledgement(response, id)
      if (generation !== mutationGeneration.current) return
      setQnrs((prev) =>
        prev.map((q) => (q.id === id ? { ...q, deleted_at: null } : q))
      )
      setMutationMessage('Questionnaire restored.')
    } catch (error: unknown) {
      if (generation !== mutationGeneration.current) return
      setRestoreErrors((prev) => ({
        ...prev,
        [id]:
          error instanceof Error && !(error instanceof TypeError)
            ? error.message
            : 'Could not confirm the restore. Try again.',
      }))
    } finally {
      if (generation === mutationGeneration.current) {
        restoreBusy.current.delete(id)
        setRestoringIds(new Set(restoreBusy.current))
        focusActions(id)
      }
    }
  }

  const saveMetadata = async (
    id: number,
    payload: { frameworks: string[]; subject_areas: string[] }
  ) => {
    if (!workspaceId || metadataBusy.current) return
    metadataBusy.current = true
    setEditQnr((current) =>
      current?.id === id ? { ...current, ...payload } : current
    )
    setSavingMetadata(true)
    setMetadataError(null)
    setMutationMessage(null)
    const generation = mutationGeneration.current
    try {
      const response = await fetch(
        `/api/questionnaires/${id}/metadata?workspace_id=${workspaceId}`,
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      )
      await requireAcknowledgement(response)
      if (generation !== mutationGeneration.current) return
      // The existing API canonicalizes an empty label list to Other.
      const confirmed = {
        frameworks: normalizeLabels(payload.frameworks),
        subject_areas: normalizeLabels(payload.subject_areas),
      }
      setEditQnr((current) =>
        current?.id === id ? { ...current, ...confirmed } : current
      )
      setQnrs((prev) =>
        prev.map((q) =>
          q.id === id
            ? {
                ...q,
                frameworks: confirmed.frameworks,
                subject_areas: confirmed.subject_areas,
              }
            : q
        )
      )
      setMutationMessage('Metadata saved.')
    } catch (error: unknown) {
      if (generation !== mutationGeneration.current) return
      setMetadataError(
        error instanceof Error && !(error instanceof TypeError)
          ? error.message
          : 'Could not confirm the changes. Your selections are still here. Try again.'
      )
    } finally {
      if (generation === mutationGeneration.current) {
        metadataBusy.current = false
        setSavingMetadata(false)
      }
    }
  }

  return (
    <div
      className="p-4 md:p-7"
      role="region"
      aria-label="Questionnaire registry"
    >
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">
          Questionnaires
        </h1>
        {refreshing && !loading && (
          <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />
        )}
      </div>
      {canUpload && (
        <Card className="mb-6">
          <label className="flex cursor-pointer items-center gap-3">
            <span className="text-sm font-medium text-[var(--tc-muted)]">
              Upload questionnaire (XLSX, DOCX)
            </span>
            <input
              id="qnr-upload"
              type="file"
              className="hidden"
              onChange={onFileSelected}
              disabled={uploading}
              accept=".xlsx,.xls,.docx,.doc"
            />
            <Button
              type="button"
              loading={uploading}
              aria-busy={uploading}
              data-upload-state={uploading ? 'pending' : 'idle'}
              onClick={() => document.getElementById('qnr-upload')?.click()}
            >
              {uploading
                ? actionVerb('upload', 'pending')
                : actionVerb('upload', 'idle')}
            </Button>
          </label>
        </Card>
      )}
      <Card className="mb-4">
        <div className="grid gap-2 md:grid-cols-6">
          <input
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            placeholder="Search by ID, filename, framework, subject, status"
            aria-label="Search questionnaires"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Framework"
            value={framework}
            onChange={(e) => setFramework(e.target.value)}
          >
            <option value="">All frameworks</option>
            {FRAMEWORK_OPTIONS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Subject area"
            value={subjectArea}
            onChange={(e) => setSubjectArea(e.target.value)}
          >
            <option value="">All subject areas</option>
            {SUBJECT_AREA_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <input
            type="datetime-local"
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Created from"
            value={createdFrom}
            onChange={(e) => setCreatedFrom(e.target.value)}
          />
          <input
            type="datetime-local"
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Created to"
            value={createdTo}
            onChange={(e) => setCreatedTo(e.target.value)}
          />
          <select
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">All statuses</option>
            {['uploaded', 'parsed', 'draft', 'completed', 'archived'].map(
              (st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              )
            )}
          </select>
          <select
            className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm"
            aria-label="Archive filter"
            value={archivedMode}
            onChange={(e) =>
              setArchivedMode(e.target.value as 'active' | 'include' | 'only')
            }
          >
            <option value="active">Active only</option>
            <option value="include">Include archived</option>
            <option value="only">Archived only</option>
          </select>
        </div>
      </Card>
      {mutationMessage && !editQnr && (
        <p role="status" className="mb-3 text-sm">
          {mutationMessage}
        </p>
      )}
      <Card>
        {error && (
          <div className="mb-4 rounded-xl bg-[var(--tc-danger)]/10 p-3 text-sm text-[var(--tc-danger)]">
            {error}
          </div>
        )}
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
        ) : (Array.isArray(qnrs) ? qnrs : []).length === 0 ? (
          <EmptyState
            title="No questionnaires yet"
            description={
              canUpload
                ? 'Upload XLSX or DOCX questionnaires to generate AI-assisted answers.'
                : 'Ask an editor to upload questionnaires.'
            }
            action={
              canUpload && (
                <Button
                  onClick={() => document.getElementById('qnr-upload')?.click()}
                >
                  Upload your first questionnaire
                </Button>
              )
            }
          />
        ) : (
          <>
            {canUpload && activeQnrs.length > 0 && (
              <BulkSelectionBar
                selectedCount={selectedIds.size}
                itemLabel="questionnaire"
                onClear={() => setSelectedIds(new Set())}
                onDelete={() => setBulkDeleteOpen(true)}
                deleting={bulkDeleting}
              />
            )}
            {canUpload && activeQnrs.length > 0 && (
              <div className="flex items-center gap-3 border-b border-white/10 py-2 text-sm text-[var(--tc-muted)]">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectAll}
                    ref={selectAllRef}
                    onChange={toggleSelectAll}
                    aria-label="Select all questionnaires on this page"
                    className="h-4 w-4 rounded border-[var(--tc-border)]"
                  />
                  Select all
                </label>
              </div>
            )}
            <ul className="divide-y divide-white/10">
              {(Array.isArray(qnrs) ? qnrs : []).map((q) => (
                <li
                  key={q.id}
                  className="flex flex-wrap items-start justify-between gap-4 py-3"
                >
                  {canUpload && (
                    <div
                      className="flex shrink-0 items-start pt-0.5"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {!q.deleted_at ? (
                        <input
                          type="checkbox"
                          checked={selectedIds.has(q.id)}
                          onChange={() => toggleSelect(q.id)}
                          aria-label={`Select ${q.display_id}`}
                          className="h-4 w-4 rounded border-[var(--tc-border)]"
                        />
                      ) : (
                        <span className="h-4 w-4" aria-hidden />
                      )}
                    </div>
                  )}
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/dashboard/questionnaires/${q.id}`}
                        className="w-full truncate font-medium text-[var(--tc-text)] hover:text-[var(--tc-soft)] md:w-auto md:flex-1"
                      >
                        {q.filename}
                      </Link>
                      <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs text-[var(--tc-muted)]">
                        {q.status}
                      </span>
                      {q.deleted_at && (
                        <span className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-xs text-amber-200">
                          Archived
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <DisplayIdText value={q.display_id} />
                      <CreatedTimestampText value={q.created_at} />
                    </div>
                    <CategoryChipsRow
                      frameworks={normalizeLabels(q.frameworks)}
                      subjectAreas={normalizeLabels(q.subject_areas)}
                    />
                    {restoringIds.has(q.id) && (
                      <span role="status" className="text-sm">
                        Restoring…
                      </span>
                    )}
                    {restoreErrors[q.id] && (
                      <div className="max-w-xs space-y-2">
                        <p
                          role="alert"
                          className="text-sm text-[var(--tc-danger)]"
                        >
                          {restoreErrors[q.id]}
                        </p>
                        <Button size="sm" onClick={() => restoreQnr(q.id)}>
                          Retry restore
                        </Button>
                      </div>
                    )}
                  </div>
                  <fieldset
                    disabled={restoringIds.has(q.id)}
                    className="w-full min-w-0 shrink-0 text-right md:w-auto"
                    ref={(element) => {
                      if (element) rowActions.current.set(q.id, element)
                      else rowActions.current.delete(q.id)
                    }}
                  >
                    <RegistryRowActionsMenu
                      aria-label={`Actions for ${q.display_id}`}
                      actions={[
                        {
                          id: 'copy_id',
                          label: 'Copy ID',
                          onClick: () =>
                            navigator.clipboard?.writeText(q.display_id),
                        },
                        {
                          id: 'open',
                          label: 'Open',
                          href: `/dashboard/review/${q.id}`,
                        },
                        {
                          id: 'edit_metadata',
                          label: 'Edit metadata',
                          onClick: () => {
                            setMetadataError(null)
                            setMutationMessage(null)
                            setEditQnr({
                              id: q.id,
                              display_id: q.display_id,
                              frameworks: q.frameworks,
                              subject_areas: q.subject_areas,
                            })
                          },
                        },
                        ...(q.deleted_at
                          ? [
                              {
                                id: 'restore' as const,
                                label: 'Restore',
                                onClick: () => restoreQnr(q.id),
                              },
                            ]
                          : [
                              {
                                id: 'delete' as const,
                                label: 'Delete',
                                onClick: () =>
                                  openDelete({
                                    id: q.id,
                                    display_id: q.display_id,
                                    filename: q.filename,
                                  }),
                                variant: 'danger' as const,
                              },
                            ]),
                      ]}
                    />
                  </fieldset>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      <BulkDeleteConfirmationModal
        isOpen={bulkDeleteOpen}
        onClose={() => setBulkDeleteOpen(false)}
        onConfirm={confirmBulkDelete}
        deleting={bulkDeleting}
        itemLabel="questionnaire"
        displayIds={(Array.isArray(qnrs) ? qnrs : [])
          .filter((q) => selectedIds.has(q.id))
          .map((q) => q.display_id)}
      />
      <DeleteConfirmationModal
        isOpen={!!deleteQnr}
        onClose={() => {
          setDeleteQnr(null)
          setDeleteUnmodeledWarning(null)
        }}
        onConfirm={confirmDelete}
        deleting={deleting}
        recordLabel={deleteQnr?.filename || ''}
        displayId={deleteQnr?.display_id || ''}
        dependencies={deleteDeps}
        unmodeledWarning={deleteUnmodeledWarning}
      />
      {editQnr && (
        <MetadataEditorModal
          isOpen={!!editQnr}
          onClose={closeMetadata}
          title={`Edit metadata · ${editQnr.display_id}`}
          frameworks={editQnr.frameworks ?? []}
          subjectAreas={editQnr.subject_areas ?? []}
          onSave={(payload) => saveMetadata(editQnr.id, payload)}
          saving={savingMetadata}
          saveMessage={
            savingMetadata
              ? 'Saving…'
              : mutationMessage === 'Metadata saved.'
                ? mutationMessage
                : null
          }
          error={metadataError}
        />
      )}
      <Modal
        isOpen={uploadModalOpen}
        onClose={() => {
          setUploadModalOpen(false)
          setUploadFile(null)
        }}
        title="Upload Questionnaire"
      >
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-3">
            <span className="text-lg">📋</span>
            <span className="text-sm font-medium text-[var(--tc-text)] truncate">
              {uploadFile?.name}
            </span>
          </div>

          <div>
            <p className="mb-2 text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">
              Frameworks
            </p>
            <div className="flex flex-wrap gap-1.5">
              {FRAMEWORK_OPTIONS.map((fw) => (
                <button
                  key={fw}
                  type="button"
                  onClick={() => toggleUploadFw(fw)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    uploadFrameworks.includes(fw)
                      ? 'border-[var(--tc-primary)] bg-[rgba(91,124,255,0.15)] text-[var(--tc-primary)]'
                      : 'border-[var(--tc-border)] text-[var(--tc-muted)] hover:border-[var(--tc-muted)]'
                  }`}
                >
                  {fw}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">
              Subject Areas
            </p>
            <p className="rounded-xl border border-dashed border-[var(--tc-border)] bg-white/5 px-4 py-3 text-xs text-[var(--tc-muted)]">
              Subject areas will be{' '}
              <span className="font-semibold text-[var(--tc-success)]">
                auto-detected
              </span>{' '}
              by AI after the questionnaire is parsed.
            </p>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              onClick={() => {
                setUploadModalOpen(false)
                setUploadFile(null)
              }}
              className="rounded-xl px-4 py-2 text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]"
            >
              Cancel
            </button>
            <Button onClick={confirmUpload}>
              {actionVerb('upload', 'idle')}
            </Button>
          </div>
        </div>
      </Modal>
      {uploadNotice && (
        <ToastViewport>
          <Toast
            title={uploadNotice.title}
            message={uploadNotice.message}
            type={uploadNotice.type}
            onDismiss={() => setUploadNotice(null)}
          />
        </ToastViewport>
      )}
    </div>
  )
}
