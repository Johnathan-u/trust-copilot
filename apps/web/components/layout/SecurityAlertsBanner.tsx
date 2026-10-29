'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ErrorState, LoadingState } from '@/components/ui'
import { useShellAlerts, type ShellAlert } from './ShellAlerts'

const ACTION_LABELS: Record<string, string> = {
  'auth.mfa_verify_failed': 'Failed two-factor sign-in attempt',
  'auth.mfa_confirm_failed': 'Failed 2FA setup verification',
  'auth.mfa_disable_failed': 'Failed attempt to disable 2FA',
  'auth.login_failed': 'Failed sign-in attempt',
}

export function securityNoticeLabel(alert: ShellAlert): string {
  return ACTION_LABELS[alert.action] || 'Security notice'
}

export function SecurityAlertsBanner() {
  const pathname = usePathname()
  const alerts = useShellAlerts()
  const [dismissed, setDismissed] = useState(false)
  if (pathname === '/dashboard') return null

  if (alerts.phase === 'loading') {
    return (
      <LoadingState
        hideUntilSlow
        label="Loading security notices"
        onRetry={alerts.reload}
        resetKey={alerts.loadId}
      />
    )
  }

  if (alerts.phase === 'error' && alerts.failure) {
    return (
      <div className="border-b border-tc-border px-tc-4 py-tc-3">
        <ErrorState failure={alerts.failure} onRetry={alerts.reload} />
      </div>
    )
  }

  if (dismissed || alerts.phase !== 'ready' || alerts.items.length === 0) {
    return null
  }

  const label =
    alerts.items.length === 1
      ? securityNoticeLabel(alerts.items[0])
      : `${alerts.items.length} recent security notices`

  return (
    <div
      className="flex items-center justify-between gap-4 border-b border-tc-border bg-tc-surface-raised px-4 py-2 text-sm"
      data-state="ready"
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-tc-text">Security notice:</span>
        <span className="text-tc-muted">
          {label}. If this was not you,{' '}
          <Link href="/dashboard/security" className="text-tc-text underline">
            review Security
          </Link>{' '}
          and consider changing your password.
        </span>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="min-h-tc-6 shrink-0 rounded-tc-xs px-tc-2 text-tc-label text-tc-text hover:bg-[var(--tc-hover)]"
      >
        Dismiss
      </button>
    </div>
  )
}
