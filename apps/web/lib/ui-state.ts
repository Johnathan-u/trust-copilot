import type { ApiFailurePresentation } from './api-error'

/** How long a skeleton may be the only feedback before a retry is offered. */
export const SKELETON_TIMEOUT_MS = 8000

export const RETRY_LABEL = 'Try again'

export const SLOW_LOADING_COPY = {
  eyebrow: 'Still loading',
  title: 'This is taking longer than usual',
  description: 'You can keep waiting, or try again.',
} as const

export const PARTIAL_SUCCESS_COPY = {
  eyebrow: 'Incomplete',
  title: "Some sections didn't load",
  description: 'Loaded sections stay on the page.',
} as const

export const ERROR_EYEBROW = 'Error'

export type SectionPhase = 'loading' | 'empty' | 'ready' | 'error'

export interface SectionSnapshot {
  id: string
  label: string
  phase: SectionPhase
  failure: ApiFailurePresentation | null
}

export interface FailedSection {
  id: string
  label: string
  failure: ApiFailurePresentation
}

export type PageMode =
  | { mode: 'loading' }
  | { mode: 'error'; failure: ApiFailurePresentation }
  | { mode: 'partial'; failed: FailedSection[] }
  | { mode: 'settled' }

export function skeletonPhase(
  elapsedMs: number,
  timeoutMs = SKELETON_TIMEOUT_MS
): 'loading' | 'slow' {
  if (!Number.isFinite(elapsedMs) || elapsedMs < timeoutMs) return 'loading'
  return 'slow'
}

/**
 * Primary content drives the page. A failed response is never an empty list.
 * Partial means at least one section failed and something else actually loaded,
 * including a successful empty primary while another section failed.
 * A successful empty secondary does not turn a failed primary into partial,
 * because there is nothing else to show.
 */
export function pageMode(
  primary: SectionSnapshot,
  rest: readonly SectionSnapshot[] = []
): PageMode {
  if (primary.phase === 'loading') return { mode: 'loading' }

  const failed: FailedSection[] = []
  for (const section of [primary, ...rest]) {
    if (section.phase === 'error' && section.failure) {
      failed.push({
        id: section.id,
        label: section.label,
        failure: section.failure,
      })
    }
  }

  const ready = [primary, ...rest].some((section) => section.phase === 'ready')
  const primarySettled = primary.phase === 'ready' || primary.phase === 'empty'
  const secondaryFailed = failed.some((item) => item.id !== primary.id)

  if (failed.length > 0 && (ready || (primarySettled && secondaryFailed))) {
    return { mode: 'partial', failed }
  }

  if (primary.phase === 'error' && primary.failure) {
    return { mode: 'error', failure: primary.failure }
  }

  if (failed.length > 0) {
    return { mode: 'error', failure: failed[0].failure }
  }

  return { mode: 'settled' }
}

export function listPhase(count: number): 'empty' | 'ready' {
  return count === 0 ? 'empty' : 'ready'
}
