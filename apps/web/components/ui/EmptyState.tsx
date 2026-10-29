'use client'

interface EmptyStateProps {
  title: string
  description: string
  action?: React.ReactNode
  className?: string
  titleAs?: 'p' | 'h2'
}

export function EmptyState({
  title,
  description,
  action,
  className = '',
  titleAs = 'p',
}: EmptyStateProps) {
  const TitleTag = titleAs === 'h2' ? 'h2' : 'p'
  return (
    <div
      data-state="empty"
      className={`flex flex-col items-center justify-center px-tc-4 py-tc-12 text-center ${className}`}
    >
      <TitleTag className="mb-tc-1 text-tc-body font-medium text-tc-text">
        {title}
      </TitleTag>
      <p className="mb-tc-4 max-w-sm text-tc-label text-tc-muted">
        {description}
      </p>
      {action && <div className="flex justify-center">{action}</div>}
    </div>
  )
}
