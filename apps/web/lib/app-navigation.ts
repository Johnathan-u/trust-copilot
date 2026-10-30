/**
 * One route list for the application sidebar, the wide top bar, and the
 * command palette. Permission flags match the sidebar rules that already
 * gated Requests and Admin.
 */

export const APP_NAV_DOCK_MIN_PX = 768

/** Matches Tailwind `md`. Viewports below this use the navigation drawer. */
export const APP_NAV_COMPACT_MEDIA = `(max-width: ${APP_NAV_DOCK_MIN_PX - 1}px)`

export const APP_NAV_DOCK_MEDIA = `(min-width: ${APP_NAV_DOCK_MIN_PX}px)`

/**
 * Complementary region that holds the workspace switcher and the application
 * navigation. Named so it is not announced with the same label as the nav.
 */
export const APP_SIDEBAR_LANDMARK_LABEL = 'Sidebar'

/**
 * Navigation landmark inside the sidebar. "Application" names the destination
 * set. "Main" would collide with the main content landmark.
 */
export const APP_NAV_LANDMARK_LABEL = 'Application'

export type AppNavSection = 'core' | 'compliance' | 'admin'

export type AppNavItem = {
  href: string
  label: string
  icon: string
  section: AppNavSection
  requiresEdit?: boolean
  requiresAdmin?: boolean
}

export type AppNavPermissions = {
  can_edit: boolean
  can_admin: boolean
}

export const appNavItems: readonly AppNavItem[] = [
  { href: '/dashboard', label: 'Home', icon: '◆', section: 'core' },
  {
    href: '/dashboard/documents',
    label: 'Documents',
    icon: '📄',
    section: 'core',
  },
  {
    href: '/dashboard/questionnaires',
    label: 'Questionnaires',
    icon: '📋',
    section: 'core',
  },
  { href: '/dashboard/review', label: 'Review', icon: '✅', section: 'core' },
  {
    href: '/dashboard/deals',
    label: 'Deals',
    icon: '💼',
    section: 'core',
  },
  {
    href: '/dashboard/requests',
    label: 'Requests',
    icon: '📨',
    section: 'core',
    requiresEdit: true,
  },
  { href: '/dashboard/exports', label: 'Exports', icon: '⬇', section: 'core' },
  {
    href: '/dashboard/compliance-gaps',
    label: 'Coverage',
    icon: '📊',
    section: 'compliance',
  },
  {
    href: '/dashboard/compliance-frameworks',
    label: 'Frameworks',
    icon: '▣',
    section: 'compliance',
  },
  {
    href: '/dashboard/controls',
    label: 'Controls',
    icon: '☑',
    section: 'compliance',
  },
  {
    href: '/dashboard/trust-center',
    label: 'Trust Center',
    icon: '🛡️',
    section: 'compliance',
  },
  {
    href: '/dashboard/proof-chain',
    label: 'Proof chain',
    icon: '🔗',
    section: 'compliance',
  },
  {
    href: '/dashboard/case-studies',
    label: 'Case studies',
    icon: '📘',
    section: 'compliance',
  },
  {
    href: '/dashboard/demo-proof',
    label: 'Demo proof',
    icon: '🧪',
    section: 'compliance',
  },
  {
    href: '/dashboard/members',
    label: 'Members',
    icon: '👥',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/notifications',
    label: 'Alerts / Notifications',
    icon: '🔔',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/slack',
    label: 'Slack',
    icon: '💬',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/gmail',
    label: 'Gmail',
    icon: '📧',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/audit',
    label: 'Activity',
    icon: '📜',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/ai-governance',
    label: 'AI Insights',
    icon: '🧠',
    section: 'admin',
    requiresAdmin: true,
  },
  {
    href: '/dashboard/settings',
    label: 'Settings',
    icon: '⚙',
    section: 'admin',
    requiresAdmin: true,
  },
]

/** Account destinations that stay in the account menu, not the section list. */
export const accountNavItems: readonly { href: string; label: string }[] = [
  { href: '/dashboard/security', label: 'Account Security' },
]

export function isAppNavActive(pathname: string, href: string): boolean {
  if (!pathname) return false
  if (pathname === href) return true
  if (href === '/dashboard') return false
  return pathname.startsWith(`${href}/`)
}

export function appNavItemsFor(permissions: AppNavPermissions): AppNavItem[] {
  return appNavItems.filter((item) => {
    if (item.requiresAdmin && !permissions.can_admin) return false
    if (item.requiresEdit && !permissions.can_edit) return false
    return true
  })
}

export function appNavSectionsFor(
  permissions: AppNavPermissions
): AppNavSection[] {
  const sections: AppNavSection[] = []
  for (const item of appNavItemsFor(permissions)) {
    if (!sections.includes(item.section)) sections.push(item.section)
  }
  return sections
}
