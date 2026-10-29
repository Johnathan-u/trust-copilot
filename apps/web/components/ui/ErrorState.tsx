'use client'

import { useEffect, useRef } from 'react'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { ERROR_EYEBROW, RETRY_LABEL } from '@/lib/ui-state'
import { Button } from './Button'

export function ErrorState({
  failure,
  onRetry,
  headingLevel = 'h2',
  secondary,
}: {
  failure: ApiFailurePresentation
  onRetry: () => void
  headingLevel?: 'h1' | 'h2'
  secondary?: React.ReactNode
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const Heading = headingLevel === 'h1' ? 'h1' : 'h2'

  useEffect(() => {
    headingRef.current?.focus()
  }, [failure.kind, failure.title])

  return (
    <div
      role="alert"
      data-state="error"
      data-failure={failure.kind}
      className="flex flex-col items-center rounded-tc border border-tc-border-strong bg-tc-surface-raised px-tc-4 py-tc-6 text-center"
    >
      <p className="text-tc-caption font-semibold uppercase tracking-wider text-tc-text">
        {ERROR_EYEBROW}
      </p>
      <Heading
        ref={headingRef}
        tabIndex={-1}
        className="mt-tc-2 text-tc-title font-semibold text-tc-text"
      >
        {failure.title}
      </Heading>
      <p className="mt-tc-2 max-w-sm text-tc-label text-tc-muted">
        {failure.description}
      </p>
      <div className="mt-tc-4 flex flex-wrap items-center justify-center gap-tc-3">
        <Button type="button" onClick={onRetry}>
          {RETRY_LABEL}
        </Button>
        {secondary}
      </div>
    </div>
  )
}
