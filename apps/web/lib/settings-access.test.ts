import { describe, expect, it } from 'vitest'
import {
  settingsAccess,
  settingsAdminSections,
  settingsPersonalSections,
  settingsSectionVisible,
  type SettingsSection,
} from '@/lib/settings-access'

const allSections: SettingsSection[] = [
  ...settingsPersonalSections,
  ...settingsAdminSections,
]

describe('settings page access', () => {
  it('mounts nothing while the session is loading, including when can_admin is already true', () => {
    for (const canAdmin of [false, true]) {
      const access = settingsAccess({ loading: true, canAdmin })
      expect(access.phase).toBe('loading')
      expect(access.sections).toEqual([])
      for (const section of allSections) {
        expect(settingsSectionVisible(access, section)).toBe(false)
      }
    }
  })

  it('shows personal and admin-only sections for an admin', () => {
    const access = settingsAccess({ loading: false, canAdmin: true })
    expect(access.phase).toBe('admin')
    expect(access.sections).toEqual(allSections)
    expect(settingsSectionVisible(access, 'billing')).toBe(true)
    expect(settingsSectionVisible(access, 'create-workspace')).toBe(true)
    expect(settingsSectionVisible(access, 'account-security')).toBe(true)
    expect(settingsSectionVisible(access, 'workspace-switch')).toBe(true)
  })

  it('keeps personal sections and omits admin-only sections for a non-admin', () => {
    const access = settingsAccess({ loading: false, canAdmin: false })
    expect(access.phase).toBe('not-authorized')
    expect(access.sections).toEqual([...settingsPersonalSections])
    expect(settingsSectionVisible(access, 'account-security')).toBe(true)
    expect(settingsSectionVisible(access, 'workspace-switch')).toBe(true)
    expect(settingsSectionVisible(access, 'billing')).toBe(false)
    expect(settingsSectionVisible(access, 'create-workspace')).toBe(false)
  })
})
