import { describe, expect, it } from 'vitest'

import {
  WORKSPACE_CAP_MESSAGE,
  WORKSPACE_INVITATION_MESSAGE,
  WORKSPACE_THROTTLE_MESSAGE,
  classifyWorkspaceCreateResponse,
  formatRetryWait,
  parseRetryAfterSeconds,
} from '@/lib/workspace-create-response'

const NOW = Date.parse('2026-10-29T12:00:00.000Z')

describe('formatRetryWait', () => {
  it('reads seconds, minutes, and hours', () => {
    expect(formatRetryWait(1)).toBe('1 second')
    expect(formatRetryWait(45)).toBe('45 seconds')
    expect(formatRetryWait(60)).toBe('1 minute')
    expect(formatRetryWait(90)).toBe('1 minute 30 seconds')
    expect(formatRetryWait(120)).toBe('2 minutes')
    expect(formatRetryWait(3600)).toBe('1 hour')
    expect(formatRetryWait(3660)).toBe('1 hour 1 minute')
  })
})

describe('parseRetryAfterSeconds', () => {
  it('reads a delay and an HTTP date', () => {
    expect(parseRetryAfterSeconds('120', NOW)).toBe(120)
    expect(parseRetryAfterSeconds('  0  ', NOW)).toBe(0)
    expect(parseRetryAfterSeconds('Thu, 29 Oct 2026 12:02:00 GMT', NOW)).toBe(
      120
    )
  })

  it('returns null when the header is missing or not a wait', () => {
    expect(parseRetryAfterSeconds(null, NOW)).toBeNull()
    expect(parseRetryAfterSeconds(undefined, NOW)).toBeNull()
    expect(parseRetryAfterSeconds('   ', NOW)).toBeNull()
    expect(parseRetryAfterSeconds('later', NOW)).toBeNull()
  })

  it('does not return a negative wait for a past date', () => {
    expect(parseRetryAfterSeconds('Thu, 29 Oct 2026 11:00:00 GMT', NOW)).toBe(0)
  })
})

describe('classifyWorkspaceCreateResponse', () => {
  it('uses invitation copy for 403 and ignores the response body', () => {
    const result = classifyWorkspaceCreateResponse(
      403,
      { detail: 'Workspace creation is not available for this account.' },
      null,
      'Could not create workspace'
    )
    expect(result).toEqual({
      kind: 'invitation',
      message: WORKSPACE_INVITATION_MESSAGE,
      retryAfterSeconds: null,
    })
  })

  it('uses the maximum copy for 409', () => {
    const result = classifyWorkspaceCreateResponse(
      409,
      { detail: 'This account has reached its workspace limit.' },
      null,
      'Could not create workspace'
    )
    expect(result.kind).toBe('cap')
    expect(result.message).toBe(WORKSPACE_CAP_MESSAGE)
  })

  it('includes a readable wait when 429 carries Retry-After', () => {
    const result = classifyWorkspaceCreateResponse(
      429,
      { detail: 'Too many workspaces created recently. Try again later.' },
      '120',
      'Could not create workspace',
      NOW
    )
    expect(result.kind).toBe('throttled')
    expect(result.retryAfterSeconds).toBe(120)
    expect(result.message).toBe(
      `${WORKSPACE_THROTTLE_MESSAGE} Wait 2 minutes before trying again.`
    )
  })

  it('keeps the later wording when 429 has no usable wait', () => {
    const missing = classifyWorkspaceCreateResponse(
      429,
      { detail: 'Too many workspaces created recently. Try again later.' },
      null,
      'Could not create workspace',
      NOW
    )
    const zero = classifyWorkspaceCreateResponse(
      429,
      {},
      '0',
      'Could not create workspace',
      NOW
    )
    expect(missing.message).toBe(WORKSPACE_THROTTLE_MESSAGE)
    expect(missing.retryAfterSeconds).toBeNull()
    expect(zero.message).toBe(WORKSPACE_THROTTLE_MESSAGE)
    expect(zero.retryAfterSeconds).toBe(0)
  })

  it('keeps the existing generic message for other statuses', () => {
    expect(
      classifyWorkspaceCreateResponse(
        400,
        { detail: 'A workspace with this name already exists' },
        '30',
        'Could not create workspace'
      )
    ).toEqual({
      kind: 'generic',
      message: 'A workspace with this name already exists',
      retryAfterSeconds: null,
    })
    expect(
      classifyWorkspaceCreateResponse(
        500,
        {},
        null,
        'Failed to create workspace'
      ).message
    ).toBe('Failed to create workspace')
  })
})
