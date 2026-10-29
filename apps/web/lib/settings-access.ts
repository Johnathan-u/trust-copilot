/**
 * Settings sections for /dashboard/settings.
 * Admin-only sections stay unmounted until the session has resolved
 * and can_admin is true. Personal sections stay available to any
 * signed-in member.
 */

export const settingsAdminSections = ['billing', 'create-workspace'] as const

export const settingsPersonalSections = [
  'workspace-switch',
  'account-security',
] as const

export type SettingsAdminSection = (typeof settingsAdminSections)[number]
export type SettingsPersonalSection = (typeof settingsPersonalSections)[number]
export type SettingsSection = SettingsAdminSection | SettingsPersonalSection

export type SettingsAccessInput = {
  loading: boolean
  canAdmin: boolean
}

export type SettingsAccess =
  | { phase: 'loading'; sections: readonly [] }
  | { phase: 'admin'; sections: readonly SettingsSection[] }
  | {
      phase: 'not-authorized'
      sections: readonly SettingsPersonalSection[]
    }

const adminAndPersonal: readonly SettingsSection[] = [
  ...settingsPersonalSections,
  ...settingsAdminSections,
]

export function settingsAccess(input: SettingsAccessInput): SettingsAccess {
  if (input.loading) return { phase: 'loading', sections: [] }
  if (input.canAdmin) return { phase: 'admin', sections: adminAndPersonal }
  return { phase: 'not-authorized', sections: settingsPersonalSections }
}

export function settingsSectionVisible(
  access: SettingsAccess,
  section: SettingsSection
): boolean {
  return (access.sections as readonly SettingsSection[]).includes(section)
}
