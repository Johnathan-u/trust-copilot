/**
 * Toast announcement policy.
 *
 * Status and info use a polite live region so they do not interrupt typing.
 * Errors use an assertive alert and never auto-dismiss. Reduced motion changes
 * the CSS duration only; it does not shorten or create a dismiss timer.
 */

export const TOAST_SEVERITIES = ['success', 'info', 'warning', 'error'] as const
export type ToastSeverity = (typeof TOAST_SEVERITIES)[number]

export type ToastPoliteness = 'polite' | 'assertive'

export interface ToastLiveRegion {
  role: 'status' | 'alert'
  ariaLive: ToastPoliteness
}

/** Non-error toasts. Callers that already kept a toast until dismiss may ignore this. */
export const DEFAULT_STATUS_DISMISS_MS = 4000

export function liveRegionForSeverity(severity: ToastSeverity): ToastLiveRegion {
  if (severity === 'error') return { role: 'alert', ariaLive: 'assertive' }
  return { role: 'status', ariaLive: 'polite' }
}

/** `null` means the toast stays until the user dismisses it. */
export function autoDismissMs(severity: ToastSeverity): number | null {
  if (severity === 'error') return null
  return DEFAULT_STATUS_DISMISS_MS
}
