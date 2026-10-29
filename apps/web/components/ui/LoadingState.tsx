'use client'

import { useEffect, useState } from 'react'
import { SKELETON_TIMEOUT_MS } from '@/lib/ui-state'
import { TakingLonger } from './TakingLonger'

interface LoadingStateProps {
  label?: string
  onRetry: () => void
  resetKey?: number | string
  timeoutMs?: number
  /** Keep the region quiet until the timeout, then offer retry. */
  hideUntilSlow?: boolean
  active?: boolean
  children?: React.ReactNode
}

export function LoadingState({
  label = 'Loading',
  onRetry,
  resetKey = 0,
  timeoutMs = SKELETON_TIMEOUT_MS,
  hideUntilSlow = false,
  active = true,
  children,
}: LoadingStateProps) {
  const [slow, setSlow] = useState(false)

  useEffect(() => {
    if (!active) return
    setSlow(false)
    const id = window.setTimeout(() => setSlow(true), timeoutMs)
    return () => window.clearTimeout(id)
  }, [active, resetKey, timeoutMs])

  if (!active) return null

  if (slow) {
    return <TakingLonger onRetry={onRetry} label={label} />
  }

  if (hideUntilSlow) return null

  return (
    <div data-state="loading" aria-busy="true">
      <p className="sr-only" role="status">
        {label}
      </p>
      {children}
    </div>
  )
}
