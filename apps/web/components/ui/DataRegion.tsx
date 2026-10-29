'use client'

import type { ApiFailurePresentation } from '@/lib/api-error'
import type { FailedSection } from '@/lib/ui-state'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'
import { PartialSuccess } from './PartialSuccess'

export type DataRegionPhase =
  'loading' | 'empty' | 'ready' | 'error' | 'partial'

export function DataRegion({
  phase,
  failure,
  onRetry,
  resetKey,
  partialFailed,
  onRetrySection,
  empty,
  skeleton,
  children,
  label = 'Loading',
}: {
  phase: DataRegionPhase
  failure?: ApiFailurePresentation | null
  onRetry: () => void
  resetKey?: number | string
  partialFailed?: readonly FailedSection[]
  onRetrySection?: (id: string) => void
  empty?: React.ReactNode
  skeleton?: React.ReactNode
  children?: React.ReactNode
  label?: string
}) {
  if (phase === 'loading') {
    return (
      <LoadingState label={label} onRetry={onRetry} resetKey={resetKey}>
        {skeleton}
      </LoadingState>
    )
  }
  if (phase === 'error' && failure) {
    return <ErrorState failure={failure} onRetry={onRetry} />
  }
  if (
    phase === 'partial' &&
    partialFailed &&
    partialFailed.length > 0 &&
    onRetrySection
  ) {
    return (
      <PartialSuccess failed={partialFailed} onRetry={onRetrySection}>
        {children}
      </PartialSuccess>
    )
  }
  if (phase === 'empty') return <>{empty}</>
  return <>{children}</>
}
