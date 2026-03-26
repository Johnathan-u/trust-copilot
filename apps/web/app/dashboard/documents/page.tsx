'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card,
  Button,
  Modal,
  DocumentListSkeleton,
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
}

type DeletePreviewPayload = {
  dependencies?: Record<string, number | string>
  unmodeled_warning?: string | null
}

export default function DocumentsPage() {
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canUpload = permissions.can_edit
  const [docs, setDocs] = useState<Doc[]>([])
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
  const [deleteDoc, setDeleteDoc] = useState<Doc | null>(null)
  const [deleteDeps, setDeleteDeps] = useState<Record<string, number | string>>({})
  const [deleteUnmodeledWarning, setDeleteUnmodeledWarning] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [editDoc, setEditDoc] = useState<Doc | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const [bulkDeleting, setBulkDeleting] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadModalOpen, setUploadModalOpen] = useState(false)
  const [uploadFrameworks, setUploadFrameworks] = useState<string[]>([])
  const [uploadSubjects, setUploadSubjects] = useState<string[]>([])

  const activeDocs = docs.filter((d) => !d.deleted_at)
  const selectAll = activeDocs.length > 0 && activeDocs.every((d) => selectedIds.has(d.id))
  const selectSome = activeDocs.some((d) => selectedIds.has(d.id))
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
    else setSelectedIds(new Set(activeDocs.map((d) => d.id)))
  }

  const selectAllRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const el = selectAllRef.current
    if (el) (el as HTMLInputElement & { indeterminate?: boolean }).indeterminate = selectSome && !selectAll
  }, [selectSome, selectAll])

  const fetchDocs = useCallback(() => {
    if (workspaceId == null) {
      setLoading(false)
      return
    }
    setLoading((prev) => docs.length === 0 ? true : prev)
    setRefreshing(true)
    const params = new URLSearchParams({ workspace_id: String(workspaceId) })
    if (search.trim()) params.set('search', search.trim())
    if (framework) params.set('framework', framework)
    if (subjectArea) params.set('subject_area', subjectArea)
    if (status) params.set('status', status)
    if (createdFrom) params.set('created_from', new Date(createdFrom).toISOString())
    if (createdTo) params.set('created_to', new Date(createdTo).toISOString())
    params.set('archived', archivedMode)
    const url = `/api/documents/?${params.toString()}`
    fetch(url, { credentials: 'include' })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!res.ok) return []
        return Array.isArray(data)
          ? (data as Doc[])
          : Array.isArray((data as { items?: Doc[] })?.items)
            ? (data as { items: Doc[] }).items
            : Array.isArray((data as { documents?: Doc[] })?.documents)
              ? (data as { documents: Doc[] }).documents
              : []
      })
      .then(setDocs)
      .catch(() => setDocs([]))
      .finally(() => { setLoading(false); setRefreshing(false) })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, search, framework, subjectArea, status, createdFrom, createdTo, archivedMode])

  useEffect(() => { fetchDocs() }, [fetchDocs])

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
    setUploadFrameworks((prev) => prev.includes(fw) ? prev.filter((f) => f !== fw) : [...prev, fw])
  }
  const toggleUploadSubj = (s: string) => {
    setUploadSubjects((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s])
  }

  const confirmUpload = () => {
    if (!uploadFile || workspaceId == null) return
    setUploading(true)
    setUploadModalOpen(false)
    setError(null)
    const fd = new FormData()
    fd.append('workspace_id', String(workspaceId))
    fd.append('file', uploadFile)
    if (uploadFrameworks.length > 0) fd.append('frameworks', uploadFrameworks.join(','))
    if (uploadSubjects.length > 0) fd.append('subject_areas', uploadSubjects.join(','))
    fetch('/api/documents/upload', { method: 'POST', credentials: 'include', body: fd })
      .then(async (r) => {
        const b = await r.json().catch(() => ({}))
        return r.ok ? b : Promise.reject(new Error(b.detail || 'Upload failed'))
      })
      .then(() => fetchDocs())
      .catch((err) => setError(err instanceof Error ? err.message : 'Upload failed'))
      .finally(() => { setUploading(false); setUploadFile(null) })
  }

  const openDelete = (doc: Doc) => {
    setDeleteDoc(doc)
    setDeleteUnmodeledWarning(null)
    if (!workspaceId) return
    fetch(`/api/documents/${doc.id}/delete-preview?workspace_id=${workspaceId}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.resolve({})))
      .then((data: unknown) => {
        const d = data as DeletePreviewPayload
        setDeleteDeps(d.dependencies || {})
        setDeleteUnmodeledWarning(d.unmodeled_warning ?? null)
      })
      .catch(() => setDeleteDeps({}))
  }

  const confirmDelete = async () => {
    if (!workspaceId || !deleteDoc) return
    setDeleting(true)
    try {
      const r = await fetch(`/api/documents/${deleteDoc.id}?workspace_id=${workspaceId}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = (await r.json().catch(() => ({}))) as { detail?: string; dependencies?: Record<string, number | string> }
      if (!r.ok) {
        setError((data?.detail as string) || 'Delete failed')
      } else {
        setDeleteDeps(data.dependencies || {})
        setDeleteDoc(null)
        fetchDocs()
      }
    } catch {
      setError('Delete failed')
    } finally {
      setDeleting(false)
    }
  }

  const restoreDoc = async (doc: Doc) => {
    if (!workspaceId) return
    await fetch(`/api/documents/${doc.id}/restore?workspace_id=${workspaceId}`, { method: 'POST', credentials: 'include' })
    fetchDocs()
  }

  const confirmBulkDelete = async () => {
    if (!workspaceId || selectedIds.size === 0) return
    setBulkDeleting(true)
    try {
      const r = await fetch(`/api/documents/bulk-delete?workspace_id=${workspaceId}`, {
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
        fetchDocs()
      }
    } catch {
      setError('Bulk delete failed')
    } finally {
      setBulkDeleting(false)
    }
  }

  const saveMetadata = async (doc: Doc, payload: { frameworks: string[]; subject_areas: string[] }) => {
    if (!workspaceId) return
    await fetch(`/api/documents/${doc.id}/metadata?workspace_id=${workspaceId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setEditDoc({ ...doc, frameworks: payload.frameworks, subject_areas: payload.subject_areas })
    setDocs((prev) => prev.map((d) => (d.id === doc.id ? { ...d, frameworks: payload.frameworks, subject_areas: payload.subject_areas } : d)))
  }

  return (
    <div className="p-7">
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Documents</h1>
        {refreshing && !loading && <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />}
      </div>
      {canUpload && (
        <Card className="mb-6">
          <label className="flex cursor-pointer items-center gap-3">
            <span className="text-sm font-medium text-[var(--tc-muted)]">Upload evidence document</span>
            <input
              id="doc-upload"
              type="file"
              className="hidden"
              onChange={onFileSelected}
              disabled={uploading}
              accept=".pdf,.docx,.xlsx"
            />
            <Button
              type="button"
              loading={uploading}
              onClick={(e) => { e.preventDefault(); document.getElementById('doc-upload')?.click() }}
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
            {['uploaded', 'indexing', 'indexed', 'failed', 'archived'].map((st) => <option key={st} value={st}>{st}</option>)}
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
          <DocumentListSkeleton />
        ) : docs.length === 0 ? (
          <EmptyState
            title="No documents yet"
            description={canUpload
              ? 'Upload PDF, DOCX, or XLSX files to use as evidence for questionnaire answers.'
              : 'Ask an editor to upload evidence documents.'}
            action={canUpload && (
              <Button onClick={() => document.getElementById('doc-upload')?.click()}>
                Upload your first document
              </Button>
            )}
          />
        ) : (
          <>
            {canUpload && activeDocs.length > 0 && (
              <BulkSelectionBar
                selectedCount={selectedIds.size}
                itemLabel="document"
                onClear={() => setSelectedIds(new Set())}
                onDelete={() => setBulkDeleteOpen(true)}
                deleting={bulkDeleting}
              />
            )}
            {canUpload && activeDocs.length > 0 && (
              <div className="flex items-center gap-3 border-b border-white/10 py-2 text-sm text-[var(--tc-muted)]">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectAll}
                    ref={selectAllRef}
                    onChange={toggleSelectAll}
                    aria-label="Select all documents on this page"
                    className="h-4 w-4 rounded border-[var(--tc-border)]"
                  />
                  Select all
                </label>
              </div>
            )}
            <ul className="divide-y divide-white/10">
            {(Array.isArray(docs) ? docs : []).map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-4 py-3">
                {canUpload && (
                  <div className="flex shrink-0 items-start pt-0.5" onClick={(e) => e.stopPropagation()}>
                    {!d.deleted_at ? (
                      <input
                        type="checkbox"
                        checked={selectedIds.has(d.id)}
                        onChange={() => toggleSelect(d.id)}
                        aria-label={`Select ${d.display_id}`}
                        className="h-4 w-4 rounded border-[var(--tc-border)]"
                      />
                    ) : (
                      <span className="h-4 w-4" aria-hidden />
                    )}
                  </div>
                )}
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium text-[var(--tc-text)]">{d.filename}</span>
                    <span className={d.status === 'failed' ? 'rounded-xl border border-[var(--tc-danger)]/50 bg-[var(--tc-danger)]/10 px-2 py-1 text-xs text-[var(--tc-danger)] shrink-0' : 'rounded-xl border border-[var(--tc-border)] bg-white/5 px-2 py-1 text-xs text-[var(--tc-muted)] shrink-0'}>
                    {d.status === 'failed' ? 'Indexing failed' : d.status}
                    </span>
                    {d.deleted_at && <span className="rounded-xl border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-xs text-amber-200">Archived</span>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <DisplayIdText value={d.display_id} />
                    <CreatedTimestampText value={d.created_at} />
                    <span className="text-xs text-[var(--tc-muted)] uppercase">{d.file_type || 'file'}</span>
                  </div>
                  <CategoryChipsRow frameworks={normalizeLabels(d.frameworks)} subjectAreas={normalizeLabels(d.subject_areas)} />
                {d.status === 'failed' && d.index_error && (
                  <p className="text-xs text-[var(--tc-muted)]" title={d.index_error}>{d.index_error}</p>
                )}
                </div>
                <RegistryRowActionsMenu
                  aria-label={`Actions for ${d.display_id}`}
                  actions={[
                    { id: 'copy_id', label: 'Copy ID', onClick: () => navigator.clipboard?.writeText(d.display_id) },
                    { id: 'edit_metadata', label: 'Edit metadata', onClick: () => setEditDoc(d) },
                    ...(d.deleted_at
                      ? [{ id: 'restore' as const, label: 'Restore', onClick: () => restoreDoc(d) }]
                      : [{ id: 'delete' as const, label: 'Delete', onClick: () => openDelete(d), variant: 'danger' as const }]),
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
        itemLabel="document"
        displayIds={docs.filter((d) => selectedIds.has(d.id)).map((d) => d.display_id)}
      />
      <DeleteConfirmationModal
        isOpen={!!deleteDoc}
        onClose={() => { setDeleteDoc(null); setDeleteUnmodeledWarning(null) }}
        onConfirm={confirmDelete}
        deleting={deleting}
        recordLabel={deleteDoc?.filename || ''}
        displayId={deleteDoc?.display_id || ''}
        dependencies={deleteDeps}
        unmodeledWarning={deleteUnmodeledWarning}
      />
      {editDoc && (
        <MetadataEditorModal
          isOpen={!!editDoc}
          onClose={() => setEditDoc(null)}
          title={`Edit metadata · ${editDoc.display_id}`}
          frameworks={normalizeLabels(editDoc.frameworks)}
          subjectAreas={normalizeLabels(editDoc.subject_areas)}
          onSave={(payload) => saveMetadata(editDoc, payload)}
        />
      )}
      <Modal isOpen={uploadModalOpen} onClose={() => { setUploadModalOpen(false); setUploadFile(null) }} title="Upload Evidence Document">
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-3">
            <span className="text-lg">📄</span>
            <span className="text-sm font-medium text-[var(--tc-text)] truncate">{uploadFile?.name}</span>
          </div>

          <div>
            <p className="mb-2 text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">Frameworks</p>
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
            <p className="mb-2 text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">Subject Areas</p>
            <div className="flex flex-wrap gap-1.5">
              {SUBJECT_AREA_OPTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => toggleUploadSubj(s)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    uploadSubjects.includes(s)
                      ? 'border-[var(--tc-success)] bg-[rgba(16,185,129,0.15)] text-[var(--tc-success)]'
                      : 'border-[var(--tc-border)] text-[var(--tc-muted)] hover:border-[var(--tc-muted)]'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              onClick={() => { setUploadModalOpen(false); setUploadFile(null) }}
              className="rounded-xl px-4 py-2 text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]"
            >
              Cancel
            </button>
            <Button onClick={confirmUpload}>
              Upload
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
