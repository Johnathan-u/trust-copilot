/**
 * Outcome of a destructive confirm after `onConfirm` settles.
 *
 * The dialog closes either way so it cannot stay in a loading state, and so an
 * error toast is not left under the dialog's inert background. Focus returns to
 * the control that opened the dialog, which is the dialog primitive's close
 * behavior. Errors use the same persistent announcement as other API failures.
 */

import { apiErrorAnnouncement } from './api-error'

export const DESTRUCTIVE_CONFIRM_ERROR_TITLE = 'Action failed'
export const DESTRUCTIVE_CONFIRM_ERROR_FALLBACK =
  'Could not complete that action.'

export interface DestructiveConfirmErrorToast {
  title: typeof DESTRUCTIVE_CONFIRM_ERROR_TITLE
  message: string
  severity: 'error'
  autoDismissMs: null
}

export interface DestructiveConfirmSettlement {
  open: false
  busy: false
  announceError: boolean
  returnFocus: 'trigger'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object') return null
  return value as Record<string, unknown>
}

/**
 * Review-page `apiErrorMessage` rule, for a thrown TC-11-001 error object
 * (`code`, `message`, optional `request_id`). Other values return null so
 * `apiErrorAnnouncement` can format them.
 */
export function apiErrorInfoMessage(reason: unknown): string | null {
  const record = asRecord(reason)
  if (!record) return null
  const nested = asRecord(record.error)
  const info = nested ?? record
  if (typeof info.message !== 'string' || !info.message.trim()) return null
  if (typeof info.code !== 'string' || !info.code.trim()) return null
  const message = info.message.trim()
  const requestId = info.request_id
  if (typeof requestId === 'string' && requestId.trim()) {
    return `${message} (ref ${requestId.trim().slice(0, 8)})`
  }
  return message
}

export function destructiveConfirmErrorToast(
  reason: unknown
): DestructiveConfirmErrorToast {
  const info = apiErrorInfoMessage(reason)
  const announced = apiErrorAnnouncement(
    info ? { detail: info } : reason,
    DESTRUCTIVE_CONFIRM_ERROR_FALLBACK
  )
  let message = announced.message
  if (
    message === DESTRUCTIVE_CONFIRM_ERROR_FALLBACK &&
    typeof reason === 'string' &&
    reason.trim()
  ) {
    message = reason.trim()
  }
  return {
    title: DESTRUCTIVE_CONFIRM_ERROR_TITLE,
    message,
    severity: 'error',
    autoDismissMs: null,
  }
}

export function nextDestructiveConfirmState(
  outcome: 'fulfilled' | 'rejected'
): DestructiveConfirmSettlement {
  return {
    open: false,
    busy: false,
    announceError: outcome === 'rejected',
    returnFocus: 'trigger',
  }
}
