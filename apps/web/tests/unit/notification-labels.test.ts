import { describe, expect, it } from 'vitest'

import {
  CATEGORY_META,
  NOTIFICATION_LABELS,
  getNotificationCategory,
  getNotificationMeta,
  getNotificationTitle,
} from '@/lib/notification-labels'

describe('notification labels', () => {
  it('maps known event types to their metadata', () => {
    expect(getNotificationMeta('compliance.coverage_drop')).toMatchObject({
      severity: 'high',
      category: 'compliance',
    })
    expect(getNotificationTitle('export.completed')).toBe('Export ready')
    expect(getNotificationCategory('member.removed')).toBe('team')
  })

  it('falls back to a generic system notification for unknown events', () => {
    const meta = getNotificationMeta('totally.unknown')
    expect(meta).toEqual({
      title: 'System Notification',
      description: 'A system event occurred.',
      severity: 'low',
      category: 'system',
    })
    expect(getNotificationTitle('')).toBe('System Notification')
    expect(getNotificationCategory('nope')).toBe('system')
  })

  it('only uses declared categories and severities, with complete copy', () => {
    for (const [event, meta] of Object.entries(NOTIFICATION_LABELS)) {
      expect(event).toMatch(/^[a-z_]+\.[a-z_]+$/)
      expect(Object.keys(CATEGORY_META)).toContain(meta.category)
      expect(['high', 'medium', 'low']).toContain(meta.severity)
      expect(meta.title.trim().length).toBeGreaterThan(0)
      expect(meta.description.trim().length).toBeGreaterThan(0)
    }
  })

  it('has a label and icon for every category', () => {
    for (const meta of Object.values(CATEGORY_META)) {
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.icon.length).toBeGreaterThan(0)
    }
  })
})
