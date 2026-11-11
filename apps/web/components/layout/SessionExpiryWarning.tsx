'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui'

export function SessionExpiryWarning() {
  const { user, session_expiry, session_expiry_status } = useAuth()
  if (!user) return null
  // A new server observation gets a fresh clock sample, never the previous
  // observation's display tick.
  return (
    <ExpiryNotice key={session_expiry?.deadline ?? session_expiry_status} />
  )
}

function ExpiryNotice() {
  const { user, session_expiry, session_expiry_status, refresh } = useAuth()
  const [now, setNow] = useState(() => performance.now())
  const remaining = session_expiry ? session_expiry.deadline - now : null

  useEffect(() => {
    if (!user || !session_expiry) return
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      const left = session_expiry.deadline - performance.now()
      if (left <= 0) return
      // Wake at the warning threshold and minute boundaries, not every second.
      const delay = left > 300_000 ? left - 300_000 : left % 60_000 || 60_000
      timer = setTimeout(
        () => {
          setNow(performance.now())
          schedule()
        },
        Math.min(delay, 2_147_483_647)
      )
    }
    schedule()
    return () => clearTimeout(timer)
  }, [user, session_expiry])

  if (!user || (remaining !== null && remaining > 300_000)) return null
  // Older responses without timing metadata never become an invented countdown.
  if (!session_expiry_status) return null
  const unavailable = session_expiry_status === 'unavailable'
  const checking =
    session_expiry_status === 'checking' ||
    (remaining !== null && remaining <= 0)
  const minutes = Math.ceil((remaining ?? 0) / 60_000)

  return (
    <div
      role="status"
      aria-label="Session expiry"
      className="flex flex-wrap items-center justify-between gap-tc-3 border-b border-tc-border bg-tc-surface-raised px-tc-4 py-tc-2 text-tc-label text-tc-text"
    >
      <p>
        {unavailable
          ? 'Could not check when your session expires. Save your work and try again.'
          : checking
            ? 'Checking whether your session has expired…'
            : `Your session expires in ${minutes <= 1 ? 'less than a minute' : `about ${minutes} minutes`}. Save your work. You’ll need to sign in again.`}
      </p>
      {unavailable && (
        <Button
          type="button"
          variant="secondary"
          onClick={() => void refresh()}
        >
          Check session
        </Button>
      )}
    </div>
  )
}
