/** Normalize FastAPI / proxy error JSON for display. */

import {
  autoDismissMs,
  liveRegionForSeverity,
  type ToastLiveRegion,
  type ToastSeverity,
} from './toast'

/**
 * API failures and denials are shown with the danger status token
 * (`--tc-danger` on `--tc-danger-surface` or a neutral surface).
 * The helper does not change the formatted message.
 */
export const API_ERROR_STATUS = 'danger' as const

export type ApiErrorStatus = typeof API_ERROR_STATUS

export function apiErrorPresentation(
  data: unknown,
  fallback = 'Request failed'
): { message: string; status: ApiErrorStatus } {
  return {
    message: formatApiErrorDetail(data, fallback),
    status: API_ERROR_STATUS,
  }
}

/**
 * Same safe message as `formatApiErrorDetail`, announced as an error toast.
 * Errors stay until the user dismisses them. The formatted string is unchanged.
 */
export function apiErrorAnnouncement(
  data: unknown,
  fallback = 'Request failed'
): {
  message: string
  severity: Extract<ToastSeverity, 'error'>
  live: ToastLiveRegion
  autoDismissMs: null
} {
  if (autoDismissMs('error') !== null)
    throw new Error('error announcements must stay until dismissed')
  return {
    message: formatApiErrorDetail(data, fallback),
    severity: 'error',
    live: liveRegionForSeverity('error'),
    autoDismissMs: null,
  }
}

export function formatApiErrorDetail(
  data: unknown,
  fallback = 'Request failed'
): string {
  if (!data || typeof data !== 'object') return fallback
  const rec = data as Record<string, unknown>
  const d = rec.detail
  if (typeof d === 'string') return d
  if (typeof rec.message === 'string' && !d) return rec.message
  if (Array.isArray(d) && d.length > 0) {
    const first = d[0]
    if (first && typeof first === 'object' && 'msg' in first) {
      const m = (first as { msg?: unknown }).msg
      if (typeof m === 'string') return m
    }
    return JSON.stringify(d)
  }
  if (d && typeof d === 'object' && 'msg' in d) {
    const m = (d as { msg?: unknown }).msg
    if (typeof m === 'string') return m
  }
  return fallback
}

/** Throw when a mutation response failed, using the API body or status text. */
export async function throwIfResponseNotOk(response: Response): Promise<void> {
  if (response.ok) return
  const data = await response.json().catch(() => null)
  const fallback = response.statusText.trim() || 'Request failed'
  throw new Error(formatApiErrorDetail(data, fallback))
}

/**
 * Neutral page-state copy for a failed read.
 * The strings do not include status codes, role names, or permission flags,
 * and they do not echo the response body.
 */
export const API_FAILURE_KINDS = [
  'offline',
  'forbidden',
  'not_found',
  'server',
  'rejected',
] as const

export type ApiFailureKind = (typeof API_FAILURE_KINDS)[number]

export interface ApiFailurePresentation {
  kind: ApiFailureKind
  title: string
  description: string
}

const FAILURE_COPY: Record<
  ApiFailureKind,
  { title: string; description: string }
> = {
  offline: {
    title: 'Offline',
    description: 'The service could not be reached. Try again.',
  },
  forbidden: {
    title: 'This section is not available',
    description: 'It cannot be opened from this account.',
  },
  not_found: {
    title: 'We could not find that',
    description: 'It may have been moved or removed.',
  },
  server: {
    title: 'Something went wrong',
    description: 'The service could not complete this request. Try again.',
  },
  rejected: {
    title: 'Could not load this',
    description: 'The request did not succeed. Try again.',
  },
}

export const MALFORMED_RESPONSE_DESCRIPTION =
  'The response could not be read. Try again.'

export function presentHttpFailure(input: {
  status?: number | null
  offline?: boolean
  malformed?: boolean
}): ApiFailurePresentation {
  if (input.offline) return { kind: 'offline', ...FAILURE_COPY.offline }
  if (input.malformed) {
    return {
      kind: 'rejected',
      title: FAILURE_COPY.rejected.title,
      description: MALFORMED_RESPONSE_DESCRIPTION,
    }
  }
  const status = input.status ?? 0
  if (status === 403) return { kind: 'forbidden', ...FAILURE_COPY.forbidden }
  if (status === 404) return { kind: 'not_found', ...FAILURE_COPY.not_found }
  if (status >= 500 && status <= 599) {
    return { kind: 'server', ...FAILURE_COPY.server }
  }
  if (status === 0) return { kind: 'offline', ...FAILURE_COPY.offline }
  return { kind: 'rejected', ...FAILURE_COPY.rejected }
}

export class ApiRequestError extends Error {
  readonly failure: ApiFailurePresentation

  constructor(failure: ApiFailurePresentation) {
    super(failure.title)
    this.name = 'ApiRequestError'
    this.failure = failure
  }
}
