'use client'

import { useEffect, useRef } from 'react'

import { Button } from '@/components/ui'
import { WORKSPACE_CREATION_UNAVAILABLE_MESSAGE } from '@/lib/workspace-creation-policy'

export function WorkspaceCreationLoading({
  className = 'text-sm text-[var(--tc-text)]',
}: {
  className?: string
}) {
  return (
    <p
      role="status"
      data-testid="workspace-creation-loading"
      className={className}
    >
      Loading
    </p>
  )
}

/** Shown when the policy read fails. Copy stays free of counts and windows. */
export function WorkspaceCreationUnavailable({
  onRetry,
}: {
  onRetry: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <div
      ref={ref}
      tabIndex={-1}
      role="alert"
      data-testid="workspace-creation-unavailable"
      className="rounded-tc-sm border border-tc-border-strong p-tc-4 text-tc-label text-tc-text focus:outline focus:outline-2 focus:outline-offset-2"
      style={{
        background: 'var(--tc-surface-raised)',
        outlineColor: 'var(--tc-focus)',
      }}
    >
      <p className="font-semibold">Could not check</p>
      <p className="mt-tc-1">{WORKSPACE_CREATION_UNAVAILABLE_MESSAGE}</p>
      <Button type="button" className="mt-tc-4" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}
