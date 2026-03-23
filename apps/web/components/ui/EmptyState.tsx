'use client'

interface EmptyStateProps {
  title: string
  description: string
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ title, description, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-12 px-6 text-center ${className}`}>
      <p className="text-base font-medium text-[var(--tc-text)] mb-1">{title}</p>
      <p className="text-sm text-[var(--tc-muted)] max-w-sm mb-4">{description}</p>
      {action && <div className="flex justify-center">{action}</div>}
    </div>
  )
}
