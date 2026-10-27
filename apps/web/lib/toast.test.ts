import { describe, expect, it } from 'vitest'
import { apiErrorAnnouncement } from '@/lib/api-error'
import {
  autoDismissMs,
  DEFAULT_STATUS_DISMISS_MS,
  liveRegionForSeverity,
  persistentToastRegions,
  TOAST_ALERT_REGION_ID,
  TOAST_STATUS_REGION_ID,
  toastRegionId,
} from '@/lib/toast'

describe('toast announcement policy', () => {
  it('uses a polite status region for success, info and warning', () => {
    for (const severity of ['success', 'info', 'warning'] as const) {
      expect(liveRegionForSeverity(severity)).toEqual({
        role: 'status',
        ariaLive: 'polite',
      })
      expect(autoDismissMs(severity)).toBe(DEFAULT_STATUS_DISMISS_MS)
    }
  })

  it('uses an assertive alert for errors and does not auto-dismiss them', () => {
    expect(liveRegionForSeverity('error')).toEqual({
      role: 'alert',
      ariaLive: 'assertive',
    })
    expect(autoDismissMs('error')).toBeNull()
    expect(autoDismissMs('error', { hasAction: true })).toBeNull()
  })

  it('mounts one polite region and one assertive region before toast text', () => {
    const regions = persistentToastRegions()
    expect(regions.map((region) => region.id)).toEqual([
      TOAST_STATUS_REGION_ID,
      TOAST_ALERT_REGION_ID,
    ])
    expect(new Set(regions.map((region) => region.role)).size).toBe(2)
    for (const severity of ['success', 'info', 'warning'] as const) {
      expect(toastRegionId(severity)).toBe(TOAST_STATUS_REGION_ID)
      expect(liveRegionForSeverity(severity).ariaLive).toBe('polite')
    }
    expect(toastRegionId('error')).toBe(TOAST_ALERT_REGION_ID)
    expect(TOAST_STATUS_REGION_ID).not.toBe(TOAST_ALERT_REGION_ID)
  })

  it('does not auto-dismiss a toast that has an action button', () => {
    for (const severity of ['success', 'info', 'warning'] as const) {
      expect(autoDismissMs(severity, { hasAction: true })).toBeNull()
      expect(autoDismissMs(severity, { hasAction: false })).toBe(
        DEFAULT_STATUS_DISMISS_MS
      )
    }
    expect(DEFAULT_STATUS_DISMISS_MS).toBe(4000)
  })

  it('maps an API error onto the assertive, persistent announcement', () => {
    const announced = apiErrorAnnouncement(
      { detail: 'Denied for this workspace' },
      'Request failed'
    )
    expect(announced).toEqual({
      message: 'Denied for this workspace',
      severity: 'error',
      live: { role: 'alert', ariaLive: 'assertive' },
      autoDismissMs: null,
    })
    expect(
      apiErrorAnnouncement(
        { detail: [{ msg: 'Name is required' }] },
        'Request failed'
      ).message
    ).toBe('Name is required')
    expect(apiErrorAnnouncement(null, 'Request failed').message).toBe(
      'Request failed'
    )
  })
})
