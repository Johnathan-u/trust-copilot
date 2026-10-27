/** Normalize FastAPI / proxy error JSON for display. */

import { autoDismissMs, liveRegionForSeverity, type ToastLiveRegion, type ToastSeverity } from './toast'

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
): { message: string; severity: Extract<ToastSeverity, 'error'>; live: ToastLiveRegion; autoDismissMs: null } {
  if (autoDismissMs('error') !== null) throw new Error('error announcements must stay until dismissed')
  return {
    message: formatApiErrorDetail(data, fallback),
    severity: 'error',
    live: liveRegionForSeverity('error'),
    autoDismissMs: null,
  }
}

export function formatApiErrorDetail(data: unknown, fallback = 'Request failed'): string {
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
