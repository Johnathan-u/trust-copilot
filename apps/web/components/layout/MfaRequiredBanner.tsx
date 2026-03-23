'use client'

import Link from 'next/link'
import { useAuth } from '@/contexts/AuthContext'

export function MfaRequiredBanner() {
  const { mfa_required_for_workspace } = useAuth()
  if (!mfa_required_for_workspace) return null

  return (
    <div
      className="flex items-center justify-between gap-4 border-b border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-2 text-sm"
      style={{ borderLeft: '4px solid #f59e0b' }}
    >
      <span className="text-[var(--tc-text)]">
        This workspace requires two-factor authentication. Please set it up in{' '}
        <Link href="/dashboard/settings" className="font-medium text-[var(--tc-soft)] underline">
          Settings
        </Link>
        .
      </span>
    </div>
  )
}
