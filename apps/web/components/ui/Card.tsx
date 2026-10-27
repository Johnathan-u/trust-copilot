'use client'

interface CardProps {
  children: React.ReactNode
  className?: string
  padding?: 'none' | 'sm' | 'md' | 'lg'
  onClick?: React.MouseEventHandler<HTMLDivElement>
}

const paddingMap = {
  none: '',
  sm: 'p-tc-4',
  md: 'p-tc-6',
  lg: 'p-tc-8',
}

export function Card({
  children,
  className = '',
  padding = 'md',
  onClick,
}: CardProps) {
  return (
    <div
      className={`rounded-tc border border-tc-border shadow-[var(--tc-shadow)] backdrop-blur-[20px] ${paddingMap[padding]} ${className}`}
      style={{ background: 'var(--tc-panel)' }}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  )
}
