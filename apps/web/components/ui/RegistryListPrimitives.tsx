'use client'

import { useMemo } from 'react'
import { Button } from './Button'
import { Modal } from './Modal'
import { TagChip, type TagData } from './TagChip'
import { formatCreatedAt } from '@/lib/listMetadata'
import { FRAMEWORK_OPTIONS, SUBJECT_AREA_OPTIONS } from '@/lib/listMetadata'

export function DisplayIdText({ value }: { value: string }) {
  return (
    <code className="rounded-md border border-[var(--tc-border)] bg-white/5 px-2 py-0.5 text-xs text-[var(--tc-soft)]">
      {value}
    </code>
  )
}

export function CreatedTimestampText({ value }: { value: string | null | undefined }) {
  return <span className="text-xs text-[var(--tc-muted)]">{formatCreatedAt(value)}</span>
}

export function CategoryChipsRow({
  frameworks,
  subjectAreas,
}: {
  frameworks: string[]
  subjectAreas: string[]
}) {
  const items = useMemo((): TagData[] => {
    const out: TagData[] = []
    let id = 0
    for (const label of frameworks) {
      out.push({
        id: id++,
        category: 'framework',
        key: label.toLowerCase().replace(/\s+/g, '_'),
        label,
        source: 'manual',
        confidence: null,
        approved: true,
      })
    }
    for (const label of subjectAreas) {
      out.push({
        id: id++,
        category: 'topic',
        key: label.toLowerCase().replace(/\s+/g, '_'),
        label,
        source: 'manual',
        confidence: null,
        approved: true,
      })
    }
    return out
  }, [frameworks, subjectAreas])

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {items.map((t) => (
        <TagChip key={`${t.category}:${t.key}`} tag={t} size="xs" />
      ))}
    </div>
  )
}

export type DeleteDependencyMap = Record<string, number | string>

export function DeleteConfirmationModal({
  isOpen,
  title,
  recordLabel,
  displayId,
  dependencies,
  unmodeledWarning,
  deleting,
  onClose,
  onConfirm,
}: {
  isOpen: boolean
  title?: string
  recordLabel: string
  displayId: string
  dependencies?: DeleteDependencyMap
  unmodeledWarning?: string | null
  deleting?: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const depEntries = Object.entries(dependencies || {}).filter(
    ([, val]) => typeof val === 'number' && val > 0
  )
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title || 'Delete record?'}>
      <div className="space-y-3">
        <div>
          <p className="font-medium text-[var(--tc-text)]">{recordLabel}</p>
          <p className="text-xs text-[var(--tc-muted)]">ID: {displayId}</p>
        </div>
        {depEntries.length > 0 && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
            <p className="mb-1 text-xs font-medium text-amber-200">This record is linked to:</p>
            <ul className="space-y-1 text-xs text-amber-100">
              {depEntries.map(([key, count]) => (
                <li key={key}>- {count} {key.replace(/_/g, ' ')}</li>
              ))}
            </ul>
          </div>
        )}
        {unmodeledWarning && (
          <p className="text-xs text-amber-200/90">{unmodeledWarning}</p>
        )}
        <p className="text-xs text-[var(--tc-muted)]">Deleting may remove active references. This action is archived as a soft delete.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function BulkSelectionBar({
  selectedCount,
  itemLabel,
  onClear,
  onDelete,
  deleting,
}: {
  selectedCount: number
  itemLabel: string
  onClear: () => void
  onDelete: () => void
  deleting?: boolean
}) {
  if (selectedCount === 0) return null
  return (
    <div
      className="sticky top-0 z-10 flex items-center justify-between gap-4 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-2 shadow-sm"
      role="status"
      aria-live="polite"
    >
      <span className="text-sm font-medium text-[var(--tc-text)]">
        {selectedCount} {itemLabel}{selectedCount === 1 ? '' : 's'} selected
      </span>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onClear} disabled={deleting}>
          Clear selection
        </Button>
        <Button variant="danger" size="sm" onClick={onDelete} disabled={deleting}>
          {deleting ? 'Deleting…' : `Delete selected`}
        </Button>
      </div>
    </div>
  )
}

export function BulkDeleteConfirmationModal({
  isOpen,
  title,
  itemLabel,
  displayIds,
  deleting,
  onClose,
  onConfirm,
}: {
  isOpen: boolean
  title?: string
  itemLabel: string
  displayIds: string[]
  deleting?: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const truncated = displayIds.length > 8 ? displayIds.slice(0, 8).join(', ') + ` and ${displayIds.length - 8} more` : displayIds.join(', ')
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title || `Delete ${displayIds.length} ${itemLabel}${displayIds.length === 1 ? '' : 's'}?`}>
      <div className="space-y-3">
        <p className="text-sm text-[var(--tc-text)]">
          You are about to archive {displayIds.length} {itemLabel}{displayIds.length === 1 ? '' : 's'}. This is a soft delete and can be restored later.
        </p>
        <div className="max-h-32 overflow-y-auto rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2">
          <p className="text-xs text-[var(--tc-muted)] font-mono">{truncated}</p>
        </div>
        <p className="text-xs text-[var(--tc-muted)]">Deleting may remove active references. This action archives the records.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function MetadataEditorModal({
  isOpen,
  title,
  frameworks,
  subjectAreas,
  onClose,
  onSave,
  saving,
}: {
  isOpen: boolean
  title?: string
  frameworks: string[]
  subjectAreas: string[]
  onClose: () => void
  onSave: (payload: { frameworks: string[]; subject_areas: string[] }) => void
  saving?: boolean
}) {
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value]
  const selectedFrameworks = frameworks
  const selectedSubjects = subjectAreas
  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title || 'Edit metadata'}>
      <div className="space-y-3">
        <div>
          <p className="mb-2 text-xs text-[var(--tc-muted)]">Frameworks</p>
          <div className="flex flex-wrap gap-1.5">
            {FRAMEWORK_OPTIONS.map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => onSave({ frameworks: toggle(selectedFrameworks, f), subject_areas: selectedSubjects })}
                className={`rounded-xl border px-2 py-1 text-xs ${selectedFrameworks.includes(f) ? 'border-[rgba(91,124,255,0.4)] bg-[rgba(91,124,255,0.2)]' : 'border-[var(--tc-border)] bg-white/5'}`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-xs text-[var(--tc-muted)]">Subject areas</p>
          <div className="flex flex-wrap gap-1.5">
            {SUBJECT_AREA_OPTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onSave({ frameworks: selectedFrameworks, subject_areas: toggle(selectedSubjects, s) })}
                className={`rounded-xl border px-2 py-1 text-xs ${selectedSubjects.includes(s) ? 'border-[rgba(91,124,255,0.4)] bg-[rgba(91,124,255,0.2)]' : 'border-[var(--tc-border)] bg-white/5'}`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={onClose} disabled={saving}>Close</Button>
        </div>
      </div>
    </Modal>
  )
}
