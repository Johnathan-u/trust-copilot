'use client'

interface ToastProps {
  title: string
  message: string
  type?: 'success' | 'error' | 'info'
  onDismiss?: () => void
}

const tone: Record<NonNullable<ToastProps['type']>, { bg: string; fg: string }> = {
  success: { bg: 'var(--tc-success-surface)', fg: 'var(--tc-success)' },
  error: { bg: 'var(--tc-danger-surface)', fg: 'var(--tc-danger)' },
  info: { bg: 'var(--tc-info-surface)', fg: 'var(--tc-info)' },
}

export function Toast({ title, message, type = 'success', onDismiss }: ToastProps) {
  const icon = tone[type]
  return (
    <div
      role={type === 'error' ? 'alert' : 'status'}
      className="fixed bottom-tc-6 right-tc-6 z-30 flex min-w-[320px] max-w-[360px] gap-tc-3 rounded-tc-sm border border-tc-border-strong p-tc-4 shadow-[var(--tc-shadow)]"
      style={{ background: 'var(--tc-surface-overlay)' }}
    >
      <div
        className="flex h-9 w-9 flex-shrink-0 place-items-center rounded-tc-xs text-tc-label font-bold"
        style={{ background: icon.bg, color: icon.fg }}
        aria-hidden
      >
        {type === 'error' ? '!' : type === 'info' ? 'i' : '✓'}
      </div>
      <div className="min-w-0">
        <strong className="block text-tc-label text-tc-text">{title}</strong>
        <span className="mt-tc-1 block text-tc-caption text-tc-muted">{message}</span>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="absolute right-tc-2 top-tc-2 rounded-tc-xs p-tc-1 text-tc-muted hover:bg-[var(--tc-hover)] hover:text-tc-text"
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  )
}
