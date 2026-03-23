'use client'

import { useEffect, useState, useRef } from 'react'
import Link from 'next/link'
import {
  Card,
  Button,
  QuestionnaireListSkeleton,
  EmptyState,
  DisplayIdText,
  CreatedTimestampText,
  CategoryChipsRow,
  DeleteConfirmationModal,
  BulkSelectionBar,
  BulkDeleteConfirmationModal,
  MetadataEditorModal,
  RegistryRowActionsMenu,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { FRAMEWORK_OPTIONS, SUBJECT_AREA_OPTIONS, normalizeLabels } from '@/lib/listMetadata'
import { formatApiErrorDetail } from '@/lib/api-error'

export default function QuestionnairesPage() {
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canUpload = permissions.can_edit
  const [qnrs, setQnrs] = useState<{ id: number; display_id: string; filename: string; status: string; created_at: string | null; deleted_at?: string | null; frameworks?: string[]; subject_areas?: string[] }[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [framework, setFramework] = useState('')
  const [subjectArea, setSubjectArea] = useState('')
  const [status, setStatus] = useState('')
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')
  const [archivedMode, setArchivedMode] = useState<'active' | 'include' | 'only'>('active')
  const [deleteQnr, setDeleteQnr] = useState<{ id: number; display_id: string; filename: string } | null>(null)
  const [deleteDeps, setDeleteDeps] = useState<Record<string, number | string>>({})
  const [deleteUnmodeledWarning, setDeleteUnmodeledWarning] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [editQnr, setEditQnr] = useState<{ id: number; display_id: string; frameworks?: string[]; subject_areas?: string[] } | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)

  const activeQnrs = (Array.isArray(qnrs) ? qnrs : []).filter((q) => !q.deleted_at)
  const selectAll = activeQnrs.length > 0 && activeQnrs.every((q) => selectedIds.has(q.id))
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
    if (el) (el as HTMLInputElement & { indeterminate?: boolean }).indeterminate = selectSome && !selectAll
  }, [selectSome, selectAll])

  useEffect(() => {
    if (workspaceId == null) {
      setLoading(false)
      return
    }
    if (qnrs.length === 0) setLoading(true)
    setRefreshing(true)
    const params = new URLSearchParams({ workspace_id: String(workspaceId) })
    if (search.trim()) params.set('search', search.trim())
    if (framework) params.set('framework', framework)
    if (subjectArea) params.set('subject_area', subjectArea)
    if (status) params.set('status', status)
    if (createdFrom) params.set('created_from', new Date(createdFrom).toISOString())
    if (createdTo) params.set('created_to', new Date(createdTo).toISOString())
    params.set('archived', archivedMode)
    fetch(`/api/questionnaires/?${params.toString()}`, { credentials: 'include' })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) {
          return []
        }
        type Qnr = { id: number; display_id: string; filename: string; status: string; created_at: string | null; frameworks?: string[]; subject_areas?: string[] }
        return Array.isArray(data)
          ? (data as Qnr[])
          : Array.isArray((data as { items?: Qnr[] })?.items)
            ? (data as { items: Qnr[] }).items
            : Array.isArray((data as { questionnaires?: Qnr[] })?.questionnaires)
              ? (data as { questionnaires: Qnr[] }).questionnaires
              : []
      })
      .then(setQnrs)
      .catch(() => setQnrs([]))
      .finally(() => { setLoading(false); setRefreshing(false) })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, search, framework, subjectArea, status, createdFrom, createdTo, archivedMode])

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || workspaceId == null) return
    setUploading(true)
    const fd = new FormData()
    fd.append('workspace_id', String(workspaceId))
    fd.append('file', file)
    setError(null)
    fetch('/api/questionnaires/upload', { method: 'POST', credentials: 'include', body: fd })
      .then(async (r) => {
        const b = await r.json().catch(() => ({}))
        return r.ok ? b : Promise.reject(new Error(formatApiErrorDetail(b, 'Upload failed')))
      })
      .then(() => {
        if (workspaceId == null) return
        const params = new URLSearchParams({ workspace_id: String(workspaceId) })
        fetch(`/api/questionnaires/?${params.toString()}`, { credentials: 'include' })
          .then((r) => (r.ok ? r.json() : []))
          .then((data) => setQnrs(Array.isArray(data) ? data : []))
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Upload failed'))
      .finally(() => { setUploading(false); e.target.value = '' })
  }

  const confirmDelete = async () => {
    if (!workspaceId || !deleteQnr) return
    setDeleting(true)
    try {
      const r = await fetch(`/api/questionnaires/${deleteQnr.id}?workspace_id=${workspaceId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
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
      const r = await fetch(`/api/questionnaires/bulk-delete?workspace_id=${workspaceId}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selectedIds) }),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        setError((data?.detail as string) || 'Bulk delete failed')
      } else {
        setSelectedIds(new Set())
        setBulkDeleteOpen(false)
        const params = new URLSearchParams({ workspace_id: String(workspaceId) })
        if (search.trim()) params.set('search', search.trim())
        if (framework) params.set('framework', framework)
        if (subjectArea) params.set('subject_area', subjectArea)
        if (status) params.set('status', status)
        if (createdFrom) params.set('created_from', new Date(createdFrom).toISOString())
        if (createdTo) params.set('created_to', new Date(createdTo).toISOString())
        params.set('archived', archivedMode)
        const res = await fetch(`/api/questionnaires/?${params.toString()}`, { credentials: 'include' })
        const json = await res.json().catch(() => ({}))
        setQnrs(Array.isArray(json) ? json : Array.isArray(json?.items) ? json.items : Array.isArray(json?.questionnaires) ? json.questionnaires : [])
      }
    } catch {
      setError('Bulk delete failed')
    } finally {
      setBulkDeleting(false)
    }
  }

  const openDelete = async (q: { id: number; display_id: string; filename: string }) => {
    setDeleteQnr(q)
    setDeleteUnmodeledWarning(null)
    if (!workspaceId) return
    const r = await fetch(`/api/questionnaires/${q.id}/delete-preview?workspace_id=${workspaceId}`, { credentials: 'include' })
    const data = await r.json().catch(() => ({}))
    setDeleteDeps(data?.dependencies || {})
    setDeleteUnmodeledWarning(data?.unmodeled_warning || null)
  }

  const restoreQnr = async (id: number) => {
    if (!workspaceId) return
    await fetch(`/api/questionnaires/${id}/restore?workspace_id=${workspaceId}`, { method: 'POST', credentials: 'include' })
    setQnrs((prev) => prev.map((q) => (q.id === id ? { ...q, deleted_at: null } : q)))
  }

  const saveMetadata = async (id: number, payload: { frameworks: string[]; subject_areas: string[] }) => {
    if (!workspaceId) return
    await fetch(`/api/questionnaires/${id}/metadata?workspace_id=${workspaceId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setQnrs((prev) =>
      prev.map((q) => (q.id === id ? { ...q, frameworks: payload.frameworks, subject_areas: payload.subject_areas } : q))
    )
  }

  return (
    <div className="p-7">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Questionnaires</h1>
        {refreshing && !loading && <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />}
      </div>
      {canUpload && (
        <Card className="mb-6">
          <label className="flex cursor-pointer items-center gap-3">
            <span className="text-sm font-medium text-[var(--tc-muted)]">Upload questionnaire (XLSX, DOCX)</span>
            <input
              id="qnr-upload"
              type="file"
              className="hidden"
              onChange={onUpload}
              disabled={uploading}
              accept=".xlsx,.xls,.docx,.doc"
            />
            <Button
              type="button"
              loading={uploading}
              onClick={() => document.getElementById('qnr-upload')?.click()}
            >
              {uploading ? 'Uploading…' : 'Choose file'}
            </Button>
          </label>
        </Card>
      )}
      <Card className="mb-4">
        <div className="grid gap-2 md:grid-cols-6">
          <input className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" placeholder="Search by ID, filename, framework, subject, status" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={framework} onChange={(e) => setFramework(e.target.value)}>
            <option value="">All frameworks</option>
            {FRAMEWORK_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          <select className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={subjectArea} onChange={(e) => setSubjectArea(e.target.value)}>
            <option value="">All subject areas</option>
            {SUBJECT_AREA_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input type="datetime-local" className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} />
          <input type="datetime-local" className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} />
          <select className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {['uploaded', 'parsed', 'draft', 'completed', 'archived'].map((st) => <option key={st} value={st}>{st}</option>)}
          </select>
          <select className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm" value={archivedMode} onChange={(e) => setArchivedMode(e.target.value as 'active' | 'include' | 'only')}>
            <option value="active">Active only</option>
            <option value="include">Include archived</option>
            <option value="only">Archived only</option>
          </select>
        </div>
      </Card>
      <Card>
        {error && (
          <div className="mb-4 rounded-xl bg-[var(--tc-danger)]/10 p-3 text-sm text-[var(--tc-danger)]">{error}</div>
        )}
        {loading ? (
          <QuestionnaireListSkeleton />
        ) : (Array.isArray(qnrs) ? qnrs : []).length === 0 ? (
          <EmptyState
            title="No questionnaires yet"
            description={canUpload
              ? 'Upload XLSX or DOCX questionnaires to generate AI-assisted answers.'
              : 'Ask an editor to upload questionnaires.'}
            action={canUpload && (
              <Button onClick={() => document.getElementById('qnr-upload')?.click()}>
                Upload your first questionnaire
              </Button>
            )}
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
              <li key={q.id} className="flex items-start justify-between gap-4 py-3">
                {canUpload && (
                  <div className="flex shrink-0 items-start pt-0.5" onClick={(e) => e.stopPropagation()}>
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
                  <div className="flex items-center justify-between gap-2">
                    <Link href={`/dashboard/questionnaires/${q.id}`} className="truncate font-medium text-[var(--tc-text)] hover:text-[var(--tc-soft)]">
                      {q.filename}
                    </Link>
                    <span className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs text-[var(--tc-muted)]">{q.status}</span>
                    {q.deleted_at && <span className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-xs text-amber-200">Archived</span>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <DisplayIdText value={q.display_id} />
                    <CreatedTimestampText value={q.created_at} />
                  </div>
                  <CategoryChipsRow frameworks={normalizeLabels(q.frameworks)} subjectAreas={normalizeLabels(q.subject_areas)} />
                </div>
                <RegistryRowActionsMenu
                  aria-label={`Actions for ${q.display_id}`}
                  actions={[
                    { id: 'copy_id', label: 'Copy ID', onClick: () => navigator.clipboard?.writeText(q.display_id) },
                    { id: 'open', label: 'Open', href: `/dashboard/review/${q.id}` },
                    { id: 'edit_metadata', label: 'Edit metadata', onClick: () => setEditQnr({ id: q.id, display_id: q.display_id, frameworks: q.frameworks, subject_areas: q.subject_areas }) },
                    ...(q.deleted_at
                      ? [{ id: 'restore' as const, label: 'Restore', onClick: () => restoreQnr(q.id) }]
                      : [{ id: 'delete' as const, label: 'Delete', onClick: () => openDelete({ id: q.id, display_id: q.display_id, filename: q.filename }), variant: 'danger' as const }]),
                  ]}
                />
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
        displayIds={(Array.isArray(qnrs) ? qnrs : []).filter((q) => selectedIds.has(q.id)).map((q) => q.display_id)}
      />
      <DeleteConfirmationModal
        isOpen={!!deleteQnr}
        onClose={() => { setDeleteQnr(null); setDeleteUnmodeledWarning(null) }}
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
          onClose={() => setEditQnr(null)}
          title={`Edit metadata · ${editQnr.display_id}`}
          frameworks={normalizeLabels(editQnr.frameworks)}
          subjectAreas={normalizeLabels(editQnr.subject_areas)}
          onSave={(payload) => saveMetadata(editQnr.id, payload)}
        />
      )}
    </div>
  )
}
