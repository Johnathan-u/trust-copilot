/**
 * Decisions that used to run as synchronous setState inside effects.
 * Components apply the result during render (or from an event handler)
 * and keep effects for external subscriptions.
 */

export function nextGeneration(
  previousKey: string | null,
  nextKey: string,
  generation: number
): { key: string; generation: number; changed: boolean } {
  if (previousKey === nextKey) {
    return { key: nextKey, generation, changed: false }
  }
  return { key: nextKey, generation: generation + 1, changed: true }
}

export function gatedLoadFlags(enabled: boolean): {
  loading: boolean
  clearFailure: boolean
} {
  return { loading: enabled, clearFailure: enabled }
}

/** A list that already has rows stays on screen and shows a refresh instead. */
export function listLoadFlags(input: { enabled: boolean; hasRows: boolean }): {
  loading: boolean | null
  refreshing: boolean
  clearFailure: boolean
} {
  if (!input.enabled) {
    return { loading: false, refreshing: false, clearFailure: false }
  }
  return {
    loading: input.hasRows ? null : true,
    refreshing: true,
    clearFailure: true,
  }
}

export function pageAfterFilterChange(
  previousQuery: string | null,
  nextQuery: string,
  page: number
): number {
  if (previousQuery === null || previousQuery === nextQuery) return page
  return 1
}

export function clampIndex(index: number, count: number): number {
  if (count <= 0) return 0
  if (index < 0) return 0
  if (index > count - 1) return count - 1
  return index
}

export function nextPaletteIndex(input: {
  open: boolean
  previouslyOpen: boolean
  index: number
  count: number
  countChanged: boolean
}): number {
  let index = input.index
  if (input.open && !input.previouslyOpen) index = 0
  if (input.countChanged || (input.open && !input.previouslyOpen)) {
    index = clampIndex(index, input.count)
  }
  return index
}

export function navOpenForPath(
  previousPath: string | null,
  nextPath: string,
  open: boolean
): boolean {
  if (previousPath !== null && previousPath !== nextPath) return false
  return open
}

export function inactiveSearch(
  query: string,
  workspaceId: number | null | undefined
): boolean {
  return query.trim().length < 2 || workspaceId == null
}

export function slowLoadingAfterChange(
  active: boolean,
  keyChanged: boolean,
  slow: boolean
): boolean {
  if (keyChanged && active) return false
  return slow
}

export function wholeSecondsBetween(
  nowMs: number,
  startedAtMs: number
): number {
  if (!Number.isFinite(nowMs) || !Number.isFinite(startedAtMs)) return 0
  return Math.max(0, Math.floor((nowMs - startedAtMs) / 1000))
}

export function shouldClearCitationTags(
  previouslyOpen: boolean,
  open: boolean
): boolean {
  return previouslyOpen && !open
}

export function trustLandingPath(slug: string): string | null {
  if (!slug) return null
  return `/trust/${slug}`
}

export const MISSING_VERIFICATION_MESSAGE = 'Missing verification link.'

export function verificationWithoutToken(token: string | null): {
  status: 'loading' | 'error'
  message: string
} {
  if (!token) {
    return { status: 'error', message: MISSING_VERIFICATION_MESSAGE }
  }
  return { status: 'loading', message: '' }
}

export const MISSING_VENDOR_TOKEN_MESSAGE =
  'No token provided. Please check your link and try again.'

export function vendorRequestWithoutToken(token: string | null): {
  loading: boolean
  error: string | null
} {
  if (!token) return { loading: false, error: MISSING_VENDOR_TOKEN_MESSAGE }
  return { loading: true, error: null }
}

export const INVALID_ANSWER_ID_MESSAGE =
  'Enter a valid answer ID (positive integer).'

export function proofChainRequest(
  raw: string
): { id: number; error?: undefined } | { id?: undefined; error: string } {
  const id = Number.parseInt(raw, 10)
  if (Number.isNaN(id) || id < 1) {
    return { error: INVALID_ANSWER_ID_MESSAGE }
  }
  return { id }
}

export interface CardDraftSource {
  title: string
  description?: string | null
  icon: string
  target_route: string
  visibility_scope?: string | null
  size?: string | null
  is_enabled?: boolean | null
}

export interface CardDraft {
  title: string
  description: string
  icon: string
  targetRoute: string
  visibility: string
  size: string
  enabled: boolean
}

export function cardFormDraft(
  card: CardDraftSource | null,
  fallbackRoute: string
): CardDraft {
  if (card) {
    return {
      title: card.title,
      description: card.description ?? '',
      icon: card.icon,
      targetRoute: card.target_route,
      visibility: card.visibility_scope ?? 'all',
      size: card.size ?? 'medium',
      enabled: card.is_enabled ?? true,
    }
  }
  return {
    title: '',
    description: '',
    icon: 'document',
    targetRoute: fallbackRoute,
    visibility: 'all',
    size: 'medium',
    enabled: true,
  }
}

export function cardFormInputsChanged(
  previous: { card: unknown; allowedMeta: unknown; isOpen: boolean } | null,
  next: { card: unknown; allowedMeta: unknown; isOpen: boolean }
): boolean {
  if (previous === null) return true
  return (
    previous.card !== next.card ||
    previous.allowedMeta !== next.allowedMeta ||
    previous.isOpen !== next.isOpen
  )
}

export function caseStudyQuoteFields(study: {
  company_name?: string | null
  quoted_results: readonly string[]
}): { organizationName: string; resultKey: string } {
  return {
    organizationName: study.company_name ?? '',
    resultKey: study.quoted_results[0] ?? '',
  }
}

export function shouldResetCaseStudyFields(
  previous: {
    id: number
    companyName: string | null | undefined
    quotedResults: readonly string[]
  },
  next: {
    id: number
    companyName: string | null | undefined
    quotedResults: readonly string[]
  }
): boolean {
  return (
    previous.id !== next.id ||
    previous.companyName !== next.companyName ||
    previous.quotedResults !== next.quotedResults
  )
}

/** Server render has no region node. The client snapshot is the live element. */
export function toastPortalTarget(
  server: boolean,
  element: HTMLElement | null
): HTMLElement | null {
  if (server) return null
  return element
}

export function subscribeToastRegion(): () => void {
  return () => {}
}
