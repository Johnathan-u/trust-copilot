'use client'

const CATEGORY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  framework: {
    bg: 'var(--tc-info-surface)',
    border: 'var(--tc-info)',
    text: 'var(--tc-info)',
  },
  topic: {
    bg: 'var(--tc-success-surface)',
    border: 'var(--tc-success)',
    text: 'var(--tc-success)',
  },
  document_type: {
    bg: 'var(--tc-warning-surface)',
    border: 'var(--tc-warning)',
    text: 'var(--tc-warning)',
  },
  custom: {
    bg: 'var(--tc-surface-sunken)',
    border: 'var(--tc-border-strong)',
    text: 'var(--tc-text)',
  },
}

export type TagData = {
  id: number
  tag_id?: number
  category: string
  key: string
  label: string
  source: string
  confidence: number | null
  approved: boolean
}

export function TagChip({
  tag,
  onRemove,
  onApprove,
  size = 'sm',
}: {
  tag: TagData
  onRemove?: () => void
  onApprove?: (approved: boolean) => void
  size?: 'sm' | 'xs'
}) {
  const style = CATEGORY_STYLES[tag.category] ?? CATEGORY_STYLES.custom

  return (
    <span
      data-size={size}
      className="inline-flex items-center gap-tc-1 whitespace-nowrap rounded-tc-xs border px-tc-2 py-tc-1 text-tc-caption font-medium"
      style={{
        background: style.bg,
        borderColor: style.border,
        color: style.text,
      }}
      title={`${tag.category}: ${tag.label}${tag.source === 'ai' ? ` (AI${tag.confidence != null ? ` ${Math.round(tag.confidence * 100)}%` : ''})` : ''}${!tag.approved ? ' — pending approval' : ''}`}
    >
      {tag.label}
      {tag.source === 'ai' && !tag.approved && <span>AI</span>}
      {onApprove && tag.source === 'ai' && !tag.approved && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onApprove(true) }}
          className="ml-tc-1"
          title="Approve tag"
          aria-label="Approve tag"
        >
          ✓
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRemove() }}
          className="ml-tc-1"
          title="Remove tag"
          aria-label="Remove tag"
        >
          ×
        </button>
      )}
    </span>
  )
}

export function TagList({
  tags,
  max = 5,
  size = 'sm',
  onRemove,
  onApprove,
}: {
  tags: TagData[]
  max?: number
  size?: 'sm' | 'xs'
  onRemove?: (tag: TagData) => void
  onApprove?: (tag: TagData, approved: boolean) => void
}) {
  if (!tags || tags.length === 0) return null
  const visible = tags.slice(0, max)
  const overflow = tags.length - max

  return (
    <span className="inline-flex flex-wrap gap-1">
      {visible.map((t) => (
        <TagChip
          key={t.id}
          tag={t}
          size={size}
          onRemove={onRemove ? () => onRemove(t) : undefined}
          onApprove={onApprove ? (approved) => onApprove(t, approved) : undefined}
        />
      ))}
      {overflow > 0 && (
        <span className="inline-flex items-center rounded-tc-xs border border-tc-border-strong bg-tc-surface-sunken px-tc-2 py-tc-1 text-tc-caption font-medium text-tc-muted">
          +{overflow}
        </span>
      )}
    </span>
  )
}
