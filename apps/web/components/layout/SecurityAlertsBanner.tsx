'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

type Alert = { id: number; action: string; occurred_at: string | null; details: string | null }

const ACTION_LABELS: Record<string, string> = {
  'auth.mfa_verify_failed': 'Failed two-factor sign-in attempt',
  'auth.mfa_confirm_failed': 'Failed 2FA setup verification',
  'auth.mfa_disable_failed': 'Failed attempt to disable 2FA',
  'auth.login_failed': 'Failed sign-in attempt',
}

export function SecurityAlertsBanner() {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [dismissed, setDismissed] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/auth/alerts', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : { alerts: [] }))
      .then((d) => setAlerts(d.alerts || []))
      .catch(() => setAlerts([]))
      .finally(() => setLoading(false))
  }, [])

  if (loading || dismissed || alerts.length === 0) return null

  const label = alerts.length === 1
    ? (ACTION_LABELS[alerts[0].action] || 'Suspicious activity')
    : `${alerts.length} recent security events`

  return (
    <div
      className="flex items-center justify-between gap-4 border-b border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-2 text-sm"
      style={{ borderLeft: '4px solid var(--tc-danger)' }}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium text-[var(--tc-text)]">Security notice:</span>
        <span className="text-[var(--tc-muted)]">
          {label}. If this wasn’t you,{' '}
          <Link href="/dashboard/security" className="text-[var(--tc-soft)] underline">
            review Security
          </Link>
          {' '}and consider changing your password.
        </span>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 rounded px-2 py-1 text-[var(--tc-muted)] hover:bg-white/10 hover:text-[var(--tc-text)]"
      >
        Dismiss
      </button>
    </div>
  )
}
