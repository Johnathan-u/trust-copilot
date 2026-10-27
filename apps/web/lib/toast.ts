/**
 * Toast announcement policy.
 *
 * Success, info and warning use a polite live region and leave after
 * DEFAULT_STATUS_DISMISS_MS (4000). Errors use an assertive alert and stay
 * until the user dismisses them.
 *
 * A toast with an action button (Undo, View, Retry, or any control other than
 * dismiss) does not auto-dismiss. A short timer can run out before a keyboard
 * user reaches that control, so the action has no time limit (WCAG 2.2.1
 * Timing Adjustable). The timer is omitted; it is not paused on hover or focus.
 *
 * Reduced motion changes the CSS duration only. It does not shorten or create
 * a dismiss timer. The Toast component owns the timer. Callers must not add
 * a second one.
 */

export const TOAST_SEVERITIES = ['success', 'info', 'warning', 'error'] as const
export type ToastSeverity = (typeof TOAST_SEVERITIES)[number]

export type ToastPoliteness = 'polite' | 'assertive'

export interface ToastLiveRegion {
  role: 'status' | 'alert'
  ariaLive: ToastPoliteness
}

export interface AutoDismissOptions {
  /** True when the toast renders an action button besides dismiss. */
  hasAction?: boolean
}

/** Non-error toasts without an action. */
export const DEFAULT_STATUS_DISMISS_MS = 4000

export function liveRegionForSeverity(severity: ToastSeverity): ToastLiveRegion {
  if (severity === 'error') return { role: 'alert', ariaLive: 'assertive' }
  return { role: 'status', ariaLive: 'polite' }
}

/** `null` means the toast stays until the user dismisses it or uses its action. */
export function autoDismissMs(severity: ToastSeverity, options?: AutoDismissOptions): number | null {
  if (severity === 'error') return null
  if (options?.hasAction) return null
  return DEFAULT_STATUS_DISMISS_MS
}
