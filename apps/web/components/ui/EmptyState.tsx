'use client'

interface EmptyStateProps {
  title: string
  description: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ title, description, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center px-tc-6 py-tc-12 text-center ${className}`}>
      <p className="mb-tc-1 text-tc-body font-medium text-tc-text">{title}</p>
      <p className="mb-tc-4 max-w-sm text-tc-label text-tc-muted">{description}</p>
      {action && <div className="flex justify-center">{action}</div>}
    </div>
  )
}
