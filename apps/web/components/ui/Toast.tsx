'use client'

interface ToastProps {
  title: string
  message: string
  type?: 'success' | 'error' | 'info'
  onDismiss?: () => void
}

export function Toast({ title, message, type = 'success', onDismiss }: ToastProps) {
  const iconBg =
    type === 'success'
      ? 'rgba(34,197,94,0.15)'
      : type === 'error'
        ? 'rgba(239,68,68,0.15)'
        : 'rgba(91,124,255,0.15)'
  const iconColor = type === 'success' ? '#86efac' : type === 'error' ? '#fca5a5' : 'var(--tc-soft)'

  return (
    <div
      className="fixed right-6 bottom-6 z-30 flex min-w-[320px] max-w-[360px] gap-3 rounded-2xl border border-[var(--tc-border)] p-4 shadow-[var(--tc-shadow)]"
      style={{
        background: 'rgba(10, 17, 30, 0.92)',
        backdropFilter: 'blur(20px)',
      }}
    >
      <div
        className="flex h-9 w-9 flex-shrink-0 place-items-center rounded-xl font-extrabold"
        style={{ background: iconBg, color: iconColor }}
      >
        ✓
      </div>
      <div className="min-w-0">
        <strong className="block text-[var(--tc-text)]">{title}</strong>
        <span className="mt-1 block text-[13px] leading-snug text-[var(--tc-muted)]">{message}</span>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="absolute right-2 top-2 rounded-lg p-1 text-[var(--tc-muted)] hover:bg-white/10 hover:text-[var(--tc-text)]"
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  )
}
