import { describe, expect, it } from 'vitest'
import {
  APP_NAV_COMPACT_MEDIA,
  APP_NAV_DOCK_MEDIA,
  APP_NAV_DOCK_MIN_PX,
  accountNavItems,
  appNavItems,
  appNavItemsFor,
  isAppNavActive,
} from './app-navigation'

describe('application navigation', () => {
  it('docks the sidebar at the 768px md breakpoint and uses a drawer below it', () => {
    expect(APP_NAV_DOCK_MIN_PX).toBe(768)
    expect(APP_NAV_DOCK_MEDIA).toBe('(min-width: 768px)')
    expect(APP_NAV_COMPACT_MEDIA).toBe('(max-width: 767px)')
  })

  it('marks the current route without treating every dashboard path as Home', () => {
    expect(isAppNavActive('/dashboard', '/dashboard')).toBe(true)
    expect(isAppNavActive('/dashboard/documents', '/dashboard')).toBe(false)
    expect(isAppNavActive('/dashboard/documents', '/dashboard/documents')).toBe(true)
    expect(isAppNavActive('/dashboard/documents/12', '/dashboard/documents')).toBe(true)
    expect(isAppNavActive('/dashboard/review', '/dashboard/review')).toBe(true)
    expect(isAppNavActive('/dashboard/reviewer', '/dashboard/review')).toBe(false)
    expect(isAppNavActive('', '/dashboard')).toBe(false)
  })

  it('keeps one permission-aware list for sidebar, top bar and palette', () => {
    const hrefs = appNavItems.map((item) => item.href)
    expect(new Set(hrefs).size).toBe(hrefs.length)
    expect(hrefs).toContain('/dashboard')
    expect(hrefs).toContain('/dashboard/settings')
    expect(accountNavItems.map((item) => item.href)).toEqual(['/dashboard/security'])

    const editor = appNavItemsFor({ can_edit: true, can_admin: false })
    expect(editor.map((item) => item.href)).toContain('/dashboard/requests')
    expect(editor.some((item) => item.section === 'admin')).toBe(false)

    const reviewer = appNavItemsFor({ can_edit: false, can_admin: false })
    expect(reviewer.map((item) => item.href)).not.toContain('/dashboard/requests')
    expect(reviewer.map((item) => item.href)).toContain('/dashboard/exports')

    const admin = appNavItemsFor({ can_edit: true, can_admin: true })
    expect(admin.map((item) => item.label)).toContain('Alerts / Notifications')
    expect(admin.map((item) => item.href)).not.toContain('/dashboard/security')
  })
})
