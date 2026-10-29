/** Copy for a refused workspace creation response. */

import { formatApiErrorDetail } from './api-error'

export const WORKSPACE_INVITATION_MESSAGE =
  'Access is set up by invitation. Ask your workspace administrator for an invite.'

export const WORKSPACE_CAP_MESSAGE =
  'You have reached the maximum number of workspaces you can administer.'

export const WORKSPACE_THROTTLE_MESSAGE =
  'There were too many attempts. Try again later.'

export const WORKSPACE_THROTTLE_READY_MESSAGE =
  'There were too many attempts. Try again later. You can try again now.'

export type WorkspaceCreateKind = 'invitation' | 'cap' | 'throttled' | 'generic'

export type WorkspaceCreateResult =
  | {
      kind: 'invitation'
      message: string
      retryAfterSeconds: null
    }
  | {
      kind: 'cap'
      message: string
      retryAfterSeconds: null
    }
  | {
      kind: 'throttled'
      message: string
      /** Seconds from Retry-After, when that header is present and understood. */
      retryAfterSeconds: number | null
    }
  | {
      kind: 'generic'
      message: string
      retryAfterSeconds: null
    }

function countPart(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? '' : 's'}`
}

/** A wait a person can read, such as "2 minutes" or "1 minute 30 seconds". */
export function formatRetryWait(totalSeconds: number): string {
  const total = Math.max(0, Math.ceil(totalSeconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const parts: string[] = []
  if (hours > 0) parts.push(countPart(hours, 'hour'))
  if (minutes > 0) parts.push(countPart(minutes, 'minute'))
  if (seconds > 0 || parts.length === 0)
    parts.push(countPart(seconds, 'second'))
  return parts.join(' ')
}

export function parseRetryAfterSeconds(
  header: string | null | undefined,
  nowMs = Date.now()
): number | null {
  if (header == null) return null
  const value = header.trim()
  if (!value) return null
  if (/^\d+$/.test(value)) return Number(value)
  const parsed = Date.parse(value)
  if (Number.isNaN(parsed)) return null
  return Math.max(0, Math.ceil((parsed - nowMs) / 1000))
}

export function throttleMessage(retryAfterSeconds: number | null): string {
  if (retryAfterSeconds == null || retryAfterSeconds <= 0) {
    return WORKSPACE_THROTTLE_MESSAGE
  }
  return `${WORKSPACE_THROTTLE_MESSAGE} Wait ${formatRetryWait(retryAfterSeconds)} before trying again.`
}

/**
 * Describe a workspace creation response for the screen.
 * Invitation, maximum, and throttled responses use fixed copy.
 * Every other status keeps the caller's existing generic message.
 */
export function classifyWorkspaceCreateResponse(
  status: number,
  data: unknown,
  retryAfterHeader: string | null | undefined,
  fallback: string,
  nowMs = Date.now()
): WorkspaceCreateResult {
  if (status === 403) {
    return {
      kind: 'invitation',
      message: WORKSPACE_INVITATION_MESSAGE,
      retryAfterSeconds: null,
    }
  }
  if (status === 409) {
    return {
      kind: 'cap',
      message: WORKSPACE_CAP_MESSAGE,
      retryAfterSeconds: null,
    }
  }
  if (status === 429) {
    const retryAfterSeconds = parseRetryAfterSeconds(retryAfterHeader, nowMs)
    return {
      kind: 'throttled',
      message: throttleMessage(retryAfterSeconds),
      retryAfterSeconds,
    }
  }
  return {
    kind: 'generic',
    message: formatApiErrorDetail(data, fallback),
    retryAfterSeconds: null,
  }
}
