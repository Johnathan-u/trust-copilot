'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'

/* ---------- Collapsible section ---------- */

function NavSection({ title, defaultOpen = false, children, storageKey }: {
  title: string; defaultOpen?: boolean; children: React.ReactNode; storageKey?: string
}) {
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
      <button type="button" onClick={toggle}
        className="flex w-full items-center justify-between px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition">
        <span>{title}</span>
        <span className={`text-[10px] transition-transform ${open ? 'rotate-0' : '-rotate-90'}`}>▼</span>
      </button>
      {open && <div className="grid gap-0.5 mt-0.5">{children}</div>}
    </div>
  )
}

/* ---------- Nav link ---------- */

function NavLink({ href, label, icon, pathname }: { href: string; label: string; icon: string; pathname: string }) {
  const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href))
  return (
    <Link href={href} scroll={false} prefetch={true}
      className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-all ${
        active
          ? 'border border-[rgba(91,124,255,0.22)] text-[var(--tc-text)] font-medium'
          : 'border border-transparent text-[var(--tc-muted)] hover:bg-white/5 hover:text-[var(--tc-text)]'
      }`}
      style={active ? { background: 'linear-gradient(180deg, rgba(91,124,255,0.12), rgba(255,255,255,0.03))' } : {}}>
      <span className="text-sm w-5 text-center flex-shrink-0">{icon}</span>
      {label}
    </Link>
  )
}

/* ---------- Sidebar ---------- */

export function Sidebar() {
  const pathname = usePathname()
  const { workspace, permissions, workspaces, switchWorkspace } = useAuth()
  const isAdmin = permissions.can_admin

  const onWorkspaceChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = parseInt(e.target.value, 10)
    if (Number.isNaN(id) || id === workspace?.id) return
    await switchWorkspace(id)
  }

  const complianceActive = ['/dashboard/compliance-gaps'].some(p => pathname.startsWith(p))
  const adminActive = ['/dashboard/members', '/dashboard/notifications', '/dashboard/slack', '/dashboard/audit', '/dashboard/security', '/dashboard/settings', '/dashboard/ai-governance'].some(p => pathname.startsWith(p))

  return (
    <aside
      className="flex min-h-0 min-w-0 flex-col gap-3 overflow-x-hidden border-r border-[var(--tc-border)] px-3 py-4"
      style={{ background: 'rgba(7, 12, 22, 0.54)', backdropFilter: 'blur(18px)' }}
    >
      {/* Workspace selector */}
      {workspaces.length > 1 ? (
        <div className="shrink-0">
          <label htmlFor="sidebar-workspace-select" className="mb-1 block px-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--tc-muted)]">
            Workspace
          </label>
          <select
            id="sidebar-workspace-select"
            key={workspace?.id ?? 'ws'}
            aria-label="Workspace"
            className="w-full cursor-pointer rounded-lg border border-[var(--tc-border)] bg-white/5 px-2.5 py-2 text-[13px] text-[var(--tc-text)] focus:border-[var(--tc-soft)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-soft)]"
            style={{ colorScheme: 'dark' }}
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
        <div className="shrink-0 rounded-lg border border-[var(--tc-border)] bg-white/5 px-2.5 py-2">
          <p className="mb-0.5 px-0.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Workspace</p>
          <p className="truncate text-[13px] font-medium text-[var(--tc-text)]">{workspace.name}</p>
        </div>
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-x-hidden overflow-y-auto pr-0.5 [scrollbar-width:thin]">
        {/* ── Core ── */}
        <nav className="grid gap-0.5">
          <NavLink href="/dashboard" label="Home" icon="◆" pathname={pathname} />
          <NavLink href="/dashboard/documents" label="Documents" icon="📄" pathname={pathname} />
          <NavLink href="/dashboard/questionnaires" label="Questionnaires" icon="📋" pathname={pathname} />
          <NavLink href="/dashboard/review" label="Review" icon="✅" pathname={pathname} />
          <NavLink href="/dashboard/exports" label="Exports" icon="⬇" pathname={pathname} />
        </nav>

        <div className="border-t border-white/5" />

        {/* ── Compliance ── */}
        <NavSection title="Compliance" defaultOpen={complianceActive} storageKey="compliance">
          <NavLink href="/dashboard/compliance-gaps" label="Coverage" icon="📊" pathname={pathname} />
        </NavSection>

        <div className="border-t border-white/5" />

        {/* ── Admin (admin-only) ── */}
        {isAdmin && (
          <NavSection title="Admin" defaultOpen={adminActive} storageKey="admin">
            <NavLink href="/dashboard/members" label="Members & Roles" icon="👥" pathname={pathname} />
            <NavLink href="/dashboard/notifications" label="Alerts" icon="🔔" pathname={pathname} />
            <NavLink href="/dashboard/slack" label="Slack" icon="💬" pathname={pathname} />
            <NavLink href="/dashboard/gmail" label="Gmail" icon="📧" pathname={pathname} />
            <NavLink href="/dashboard/audit" label="Activity" icon="📋" pathname={pathname} />
            <NavLink href="/dashboard/ai-governance" label="AI Insights" icon="🧠" pathname={pathname} />
            <NavLink href="/dashboard/settings" label="Settings" icon="⚙" pathname={pathname} />
          </NavSection>
        )}
      </div>
    </aside>
  )
}
