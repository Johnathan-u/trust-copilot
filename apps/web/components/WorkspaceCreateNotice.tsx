'use client'

import { useEffect, useRef, useState } from 'react'

import {
  WORKSPACE_INVITATION_MESSAGE,
  WORKSPACE_SALES_MAILTO,
  type WorkspaceCreateKind,
} from '@/lib/workspace-create-response'

type DenialKind = Exclude<WorkspaceCreateKind, 'generic'>

const titleFor: Record<DenialKind, string> = {
  invitation: 'Invitation needed',
  cap: 'Maximum reached',
  throttled: 'Too many attempts',
}

function InvitationCopy() {
  const marker = 'contact sales'
  const index = WORKSPACE_INVITATION_MESSAGE.lastIndexOf(marker)
  if (index < 0) {
    return <p className="mt-tc-1">{WORKSPACE_INVITATION_MESSAGE}</p>
  }
  return (
    <p className="mt-tc-1">
      {WORKSPACE_INVITATION_MESSAGE.slice(0, index)}
      <a
        href={WORKSPACE_SALES_MAILTO}
        className="font-semibold text-tc-text underline"
      >
        {marker}
      </a>
      {WORKSPACE_INVITATION_MESSAGE.slice(index + marker.length)}
    </p>
  )
}

/**
 * Inline notice for a refused workspace creation.
 * Focus moves here once per mount. Callers change `key` for a new refusal.
 * The title is text, so the meaning does not depend on the surface color.
 */
export function WorkspaceCreateNotice({
  kind,
  message,
}: {
  kind: DenialKind
  message: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])

  const calm = kind === 'invitation'
  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="alert"
      id="workspace-create-notice"
      data-testid="workspace-create-notice"
      data-notice-kind={kind}
      className="rounded-tc-sm border p-tc-4 text-tc-label text-tc-text focus:outline focus:outline-2 focus:outline-offset-2"
      style={{
        background: calm
          ? 'var(--tc-surface-raised)'
          : 'var(--tc-danger-surface)',
        borderColor: calm ? 'var(--tc-border-strong)' : 'var(--tc-danger)',
        outlineColor: 'var(--tc-focus)',
      }}
    >
      <p className="font-semibold">{titleFor[kind]}</p>
      {kind === 'invitation' ? (
        <InvitationCopy />
      ) : (
        <p className="mt-tc-1">{message}</p>
      )}
    </div>
  )
}

/**
 * Holds a create action closed until a wait elapses.
 * `blockFor` is called from the submit handler, so the next render is closed.
 */
export function useCreationBlock(onWaitEnded?: () => void) {
  const onWaitEndedRef = useRef(onWaitEnded)
  const timerRef = useRef<number | null>(null)
  const [blocked, setBlocked] = useState(false)

  useEffect(() => {
    onWaitEndedRef.current = onWaitEnded
  }, [onWaitEnded])

  useEffect(() => {
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current)
    }
  }, [])

  function blockFor(seconds: number | null) {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (seconds == null || seconds <= 0) {
      setBlocked(false)
      return
    }
    setBlocked(true)
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setBlocked(false)
      onWaitEndedRef.current?.()
    }, seconds * 1000)
  }

  return { blocked, blockFor }
}

export async function signOutToLogin() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    // The sign-in page remains available either way.
  }
  // Full page load so the next screen reads the signed-out session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- same full-load sign-out as the account menu
  window.location.assign('/login')
}
