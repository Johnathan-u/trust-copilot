import { describe, expect, it } from 'vitest'
import { apiErrorAnnouncement } from './api-error'
import { autoDismissMs, DEFAULT_STATUS_DISMISS_MS, liveRegionForSeverity } from './toast'

describe('toast announcement policy', () => {
  it('uses a polite status region for success, info and warning', () => {
    for (const severity of ['success', 'info', 'warning'] as const) {
      expect(liveRegionForSeverity(severity)).toEqual({ role: 'status', ariaLive: 'polite' })
      expect(autoDismissMs(severity)).toBe(DEFAULT_STATUS_DISMISS_MS)
    }
  })

  it('uses an assertive alert for errors and does not auto-dismiss them', () => {
    expect(liveRegionForSeverity('error')).toEqual({ role: 'alert', ariaLive: 'assertive' })
    expect(autoDismissMs('error')).toBeNull()
  })

  it('maps an API error onto the assertive, persistent announcement', () => {
    const announced = apiErrorAnnouncement({ detail: 'Denied for this workspace' }, 'Request failed')
    expect(announced).toEqual({
      message: 'Denied for this workspace',
      severity: 'error',
      live: { role: 'alert', ariaLive: 'assertive' },
      autoDismissMs: null,
    })
    expect(apiErrorAnnouncement({ detail: [{ msg: 'Name is required' }] }, 'Request failed').message).toBe(
      'Name is required'
    )
    expect(apiErrorAnnouncement(null, 'Request failed').message).toBe('Request failed')
  })
})