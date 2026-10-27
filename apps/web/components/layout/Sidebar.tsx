'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'

/* ---------- Collapsible section ---------- */

function NavSection({
  title,
  defaultOpen = false,
  children,
  storageKey,
}: {
  title: string
  defaultOpen?: boolean
  children: React.ReactNode
  storageKey?: string
}) {
  const [open, setOpen] = useState(() => {
    if (storageKey && typeof window !== 'undefined') {
      const saved = localStorage.getItem(`sidebar_${storageKey}`)
      if (saved !== null) return saved === '1'
    }
    return defaultOpen
  })
  const toggle = useCallback(() => {
    setOpen((prev) => {
      const next = !prev
      if (storageKey && typeof window !== 'undefined')
        localStorage.setItem(`sidebar_${storageKey}`, next ? '1' : '0')
      return next
    })
  }, [storageKey])
  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        className="flex min-h-tc-6 w-full items-center justify-between px-tc-2 py-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted transition-colors duration-[var(--tc-duration-fast)] hover:text-tc-text"
      >
        <span>{title}</span>
        <span
          className={`text-tc-caption transition-transform duration-[var(--tc-duration-fast)] ${open ? 'rotate-0' : '-rotate-90'}`}
        >
          ▼
        </span>
      </button>
      {open && <div className="mt-tc-1 grid gap-tc-1">{children}</div>}
    </div>
  )
}

/* ---------- Nav link ---------- */

function NavLink({
  href,
  label,
  icon,
  pathname,
}: {
  href: string
  label: string
  icon: string
  pathname: string
}) {
  const active =
    pathname === href || (href !== '/dashboard' && pathname.startsWith(href))
  return (
    <Link
      href={href}
      scroll={false}
      prefetch={true}
      className={`flex min-h-tc-6 items-center gap-tc-2 rounded-tc-xs px-tc-3 py-tc-2 text-tc-label transition-colors duration-[var(--tc-duration-fast)] ${
        active
          ? 'border border-[var(--tc-nav-active-border)] bg-[var(--tc-nav-active-bg)] font-medium text-tc-text'
          : 'border border-transparent text-tc-muted hover:bg-[var(--tc-hover)] hover:text-tc-text'
      }`}
    >
      <span className="text-sm w-5 text-center flex-shrink-0">{icon}</span>
      {label}
    </Link>
  )
}

/* ---------- Sidebar ---------- */

export function Sidebar() {
  const pathname = usePathname()
  const { workspace, permissions, workspaces, switchWorkspace } = useAuth()
  const canEdit = permissions.can_edit
  const isAdmin = permissions.can_admin

  const onWorkspaceChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = parseInt(e.target.value, 10)
    if (Number.isNaN(id) || id === workspace?.id) return
    await switchWorkspace(id)
  }

  const complianceActive = [
    '/dashboard/compliance-gaps',
    '/dashboard/compliance-frameworks',
    '/dashboard/trust-center',
    '/dashboard/proof-chain',
    '/dashboard/case-studies',
    '/dashboard/demo-proof',
  ].some((p) => pathname.startsWith(p))
  const adminActive = [
    '/dashboard/members',
    '/dashboard/notifications',
    '/dashboard/slack',
    '/dashboard/gmail',
    '/dashboard/audit',
    '/dashboard/security',
    '/dashboard/settings',
    '/dashboard/ai-governance',
  ].some((p) => pathname.startsWith(p))

  return (
    <aside
      className="flex min-h-0 min-w-0 flex-col gap-tc-3 overflow-x-hidden border-r border-tc-border px-tc-3 py-tc-4"
      style={{ background: 'var(--tc-sidebar)' }}
    >
      {/* Workspace selector */}
      {workspaces.length > 1 ? (
        <div className="shrink-0">
          <label
            htmlFor="sidebar-workspace-select"
            className="mb-tc-1 block px-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted"
          >
            Workspace
          </label>
          <select
            id="sidebar-workspace-select"
            key={workspace?.id ?? 'ws'}
            aria-label="Workspace"
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
          <p className="mb-tc-1 px-tc-1 text-tc-caption font-semibold uppercase tracking-wider text-tc-muted">
            Workspace
          </p>
          <p className="truncate text-tc-label font-medium text-tc-text">
            {workspace.name}
          </p>
        </div>
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-x-hidden overflow-y-auto pr-0.5 [scrollbar-width:thin]">
        {/* ── Core ── */}
        <nav className="grid gap-tc-1">
          <NavLink
            href="/dashboard"
            label="Home"
            icon="◆"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/documents"
            label="Documents"
            icon="📄"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/questionnaires"
            label="Questionnaires"
            icon="📋"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/review"
            label="Review"
            icon="✅"
            pathname={pathname}
          />
          {canEdit && (
            <NavLink
              href="/dashboard/requests"
              label="Requests"
              icon="📨"
              pathname={pathname}
            />
          )}
          <NavLink
            href="/dashboard/exports"
            label="Exports"
            icon="⬇"
            pathname={pathname}
          />
        </nav>

        <div className="border-t border-tc-border" />

        {/* ── Compliance ── */}
        <NavSection
          title="Compliance"
          defaultOpen={complianceActive}
          storageKey="compliance"
        >
          <NavLink
            href="/dashboard/compliance-gaps"
            label="Coverage"
            icon="📊"
            pathname={pathname}
          />
          {/* prettier-ignore */}
          <NavLink href="/dashboard/compliance-frameworks" label="Frameworks" icon="▣" pathname={pathname} />
          <NavLink
            href="/dashboard/trust-center"
            label="Trust Center"
            icon="🛡️"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/proof-chain"
            label="Proof chain"
            icon="🔗"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/case-studies"
            label="Case studies"
            icon="📘"
            pathname={pathname}
          />
          <NavLink
            href="/dashboard/demo-proof"
            label="Demo proof"
            icon="🧪"
            pathname={pathname}
          />
        </NavSection>

        <div className="border-t border-tc-border" />

        {/* ── Admin (admin-only) ── */}
        {isAdmin && (
          <NavSection
            title="Admin"
            defaultOpen={adminActive}
            storageKey="admin"
          >
            <NavLink
              href="/dashboard/members"
              label="Members"
              icon="👥"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/notifications"
              label="Alerts / Notifications"
              icon="🔔"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/slack"
              label="Slack"
              icon="💬"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/gmail"
              label="Gmail"
              icon="📧"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/audit"
              label="Activity"
              icon="📜"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/ai-governance"
              label="AI Insights"
              icon="🧠"
              pathname={pathname}
            />
            <NavLink
              href="/dashboard/settings"
              label="Settings"
              icon="⚙"
              pathname={pathname}
            />
          </NavSection>
        )}
      </div>
    </aside>
  )
}
