'use client'

const CATEGORY_STYLES: Record<string, { bg: string; border: string; text: string }> = {
  framework: {
    bg: 'rgba(91, 124, 255, 0.12)',
    border: 'rgba(91, 124, 255, 0.22)',
    text: '#7c96ff',
  },
  topic: {
    bg: 'rgba(16, 185, 129, 0.12)',
    border: 'rgba(16, 185, 129, 0.22)',
    text: '#34d399',
  },
  document_type: {
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.22)',
    text: '#fbbf24',
  },
  custom: {
    bg: 'rgba(168, 162, 158, 0.12)',
    border: 'rgba(168, 162, 158, 0.22)',
    text: '#a8a29e',
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
  const fontSize = size === 'xs' ? '10px' : '11px'
  const py = size === 'xs' ? '1px' : '2px'

  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-1.5 font-medium whitespace-nowrap"
      style={{
        background: style.bg,
        borderColor: style.border,
        color: style.text,
        fontSize,
        paddingTop: py,
        paddingBottom: py,
        opacity: tag.source === 'ai' && !tag.approved ? 0.7 : 1,
      }}
      title={`${tag.category}: ${tag.label}${tag.source === 'ai' ? ` (AI${tag.confidence != null ? ` ${Math.round(tag.confidence * 100)}%` : ''})` : ''}${!tag.approved ? ' — pending approval' : ''}`}
    >
      {tag.label}
      {tag.source === 'ai' && !tag.approved && (
        <span className="text-[9px] opacity-60">AI</span>
      )}
      {onApprove && tag.source === 'ai' && !tag.approved && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onApprove(true) }}
          className="ml-0.5 text-[10px] opacity-60 hover:opacity-100"
          title="Approve tag"
        >
          ✓
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onRemove() }}
          className="ml-0.5 text-[10px] opacity-60 hover:opacity-100"
          title="Remove tag"
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
        <span
          className="inline-flex items-center rounded-md border px-1.5 text-[11px] font-medium"
          style={{
            background: 'rgba(255,255,255,0.05)',
            borderColor: 'rgba(255,255,255,0.1)',
            color: 'var(--tc-muted)',
            paddingTop: size === 'xs' ? '1px' : '2px',
            paddingBottom: size === 'xs' ? '1px' : '2px',
          }}
        >
          +{overflow}
        </span>
      )}
    </span>
  )
}
