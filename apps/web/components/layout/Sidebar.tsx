'use client'

import { useCallback, useId, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import {
  appNavItemsFor,
  isAppNavActive,
  type AppNavItem,
  type AppNavSection,
} from '@/lib/app-navigation'

const SECTION_TITLES: Record<Exclude<AppNavSection, 'core'>, string> = {
  compliance: 'Compliance',
  admin: 'Admin',
}

function NavSection({ title, defaultOpen = false, children, storageKey }: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
  storageKey?: string
}) {
  const panelId = useId()
  const [open, setOpen] = useState(() => {
    if (storageKey && typeof window !== 'undefined') {
      const saved = localStorage.getItem(`sidebar_${storageKey}`)
      if (saved !== null) return saved === '1'
    }
    return defaultOpen
  })
  const toggle = useCallback(() => {
    setOpen(prev => {
      const next = !prev
      if (storageKey && typeof window !== 'undefined') localStorage.setItem(`sidebar_${storageKey}`, next ? '1' : '0')
      return next
    })
  }, [storageKey])
  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex min-h-tc-6 w-full items-center justify-between px-tc-2 py-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted transition-colors duration-[var(--tc-duration-fast)] hover:text-tc-text"
      >
        <span>{title}</span>
        <span aria-hidden className={`text-tc-caption transition-transform duration-[var(--tc-duration-fast)] ${open ? 'rotate-0' : '-rotate-90'}`}>▼</span>
      </button>
      <div id={panelId} hidden={!open} className="mt-tc-1 grid gap-tc-1">
        {children}
      </div>
    </div>
  )
}

function NavLink({ item, pathname, onNavigate }: { item: AppNavItem; pathname: string; onNavigate?: () => void }) {
  const active = isAppNavActive(pathname, item.href)
  return (
    <Link
      href={item.href}
      scroll={false}
      prefetch={true}
      aria-current={active ? 'page' : undefined}
      onClick={onNavigate}
      className={`flex min-h-tc-6 min-w-0 items-center gap-tc-2 rounded-tc-xs px-tc-3 py-tc-2 text-tc-label transition-colors duration-[var(--tc-duration-fast)] ${
        active
          ? 'border border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)] font-medium text-tc-text'
          : 'border border-transparent text-tc-muted hover:bg-[var(--tc-hover)] hover:text-tc-text'
      }`}
    >
      <span aria-hidden className="w-5 flex-shrink-0 text-center text-sm">{item.icon}</span>
      <span className="truncate">{item.label}</span>
    </Link>
  )
}

export function Sidebar({ className = '', onNavigate }: { className?: string; onNavigate?: () => void }) {
  const pathname = usePathname()
  const { workspace, permissions, workspaces, switchWorkspace } = useAuth()
  const items = appNavItemsFor({ can_edit: permissions.can_edit, can_admin: permissions.can_admin })
  const core = items.filter((item) => item.section === 'core')
  const compliance = items.filter((item) => item.section === 'compliance')
  const admin = items.filter((item) => item.section === 'admin')

  const onWorkspaceChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = parseInt(e.target.value, 10)
    if (Number.isNaN(id) || id === workspace?.id) return
    await switchWorkspace(id)
  }

  const complianceActive = compliance.some((item) => isAppNavActive(pathname, item.href))
  const adminActive = admin.some((item) => isAppNavActive(pathname, item.href))

  return (
    <aside
      aria-label="Application"
      data-sidebar-placement={onNavigate ? 'drawer' : 'dock'}
      className={`flex min-h-0 min-w-0 flex-col gap-tc-3 overflow-x-hidden overflow-y-auto border-r border-tc-border px-tc-3 py-tc-4 ${className}`}
      style={{ background: 'var(--tc-sidebar)' }}
    >
      {workspaces.length > 1 ? (
        <div className="shrink-0">
          <label htmlFor="sidebar-workspace-select" className="mb-tc-1 block px-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted">
            Workspace
          </label>
          <select
            id="sidebar-workspace-select"
            key={workspace?.id ?? 'ws'}
            className="w-full cursor-pointer rounded-tc-xs border border-tc-border-strong bg-tc-surface-overlay px-tc-2 py-tc-2 text-tc-label text-tc-text"
            value={workspace != null ? String(workspace.id) : ''}
            onChange={onWorkspaceChange}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={String(w.id)}>
                {w.name}
              </option>
            ))}
          </select>
        </div>
      ) : workspace ? (
        <div className="shrink-0 rounded-tc-xs border border-tc-border-strong bg-tc-surface-overlay px-tc-2 py-tc-2">
          <p className="mb-tc-1 px-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted">Workspace</p>
          <p className="truncate text-tc-label font-medium text-tc-text">{workspace.name}</p>
        </div>
      ) : null}

      <nav aria-label="Application" className="flex min-h-0 min-w-0 flex-col gap-3 pr-0.5">
        <div className="grid gap-tc-1">
          {core.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} />
          ))}
        </div>

        {compliance.length > 0 && (
          <>
            <div className="border-t border-tc-border" />
            <NavSection title={SECTION_TITLES.compliance} defaultOpen={complianceActive} storageKey="compliance">
              {compliance.map((item) => (
                <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} />
              ))}
            </NavSection>
          </>
        )}

        {admin.length > 0 && (
          <>
            <div className="border-t border-tc-border" />
            <NavSection title={SECTION_TITLES.admin} defaultOpen={adminActive} storageKey="admin">
              {admin.map((item) => (
                <NavLink key={item.href} item={item} pathname={pathname} onNavigate={onNavigate} />
              ))}
            </NavSection>
          </>
        )}
      </nav>
    </aside>
  )
}
