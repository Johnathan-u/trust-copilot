'use client'

import { useEffect, useRef } from 'react'
import { RETRY_LABEL, SLOW_LOADING_COPY } from '@/lib/ui-state'
import { Button } from './Button'

export function TakingLonger({
  onRetry,
  label = 'Loading',
}: {
  onRetry: () => void
  label?: string
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    headingRef.current?.focus()
  }, [])

  return (
    <div
      role="status"
      data-state="slow"
      className="flex flex-col items-center rounded-tc border border-tc-border-strong bg-tc-surface-raised px-tc-4 py-tc-6 text-center"
    >
      <p className="text-tc-caption font-semibold uppercase tracking-wider text-tc-text">
        {SLOW_LOADING_COPY.eyebrow}
      </p>
      <h2
        ref={headingRef}
        tabIndex={-1}
        className="mt-tc-2 text-tc-title font-semibold text-tc-text"
      >
        {SLOW_LOADING_COPY.title}
      </h2>
      <p className="mt-tc-2 max-w-sm text-tc-label text-tc-muted">
        {SLOW_LOADING_COPY.description}
      </p>
      <p className="sr-only">{label}</p>
      <Button type="button" className="mt-tc-4" onClick={onRetry}>
        {RETRY_LABEL}
      </Button>
    </div>
  )
}
