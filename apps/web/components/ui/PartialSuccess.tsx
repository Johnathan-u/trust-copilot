'use client'

import { useEffect, useRef } from 'react'
import {
  PARTIAL_SUCCESS_COPY,
  RETRY_LABEL,
  type FailedSection,
} from '@/lib/ui-state'
import { Button } from './Button'

export function PartialSuccess({
  failed,
  onRetry,
  children,
}: {
  failed: readonly FailedSection[]
  onRetry: (id: string) => void
  children?: React.ReactNode
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const focusKey = failed
    .map((section) => `${section.id}:${section.failure.kind}`)
    .join('|')

  useEffect(() => {
    headingRef.current?.focus()
  }, [focusKey])

  return (
    <div data-state="partial" className="grid gap-tc-4">
      <div
        role="alert"
        className="rounded-tc border border-tc-border-strong bg-tc-surface-raised px-tc-4 py-tc-4"
      >
        <p className="text-tc-caption font-semibold uppercase tracking-wider text-tc-text">
          {PARTIAL_SUCCESS_COPY.eyebrow}
        </p>
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="mt-tc-2 text-tc-title font-semibold text-tc-text"
        >
          {PARTIAL_SUCCESS_COPY.title}
        </h2>
        <p className="mt-tc-2 text-tc-label text-tc-muted">
          {PARTIAL_SUCCESS_COPY.description}
        </p>
        <ul className="mt-tc-4 grid gap-tc-3">
          {failed.map((section) => (
            <li
              key={section.id}
              className="flex flex-col items-start gap-tc-2 border-t border-tc-border pt-tc-3"
            >
              <p className="text-tc-label text-tc-text">
                <span className="font-semibold">{section.label}. </span>
                {section.failure.title}. {section.failure.description}
              </p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => onRetry(section.id)}
              >
                {RETRY_LABEL}: {section.label}
              </Button>
            </li>
          ))}
        </ul>
      </div>
      {children}
    </div>
  )
}
