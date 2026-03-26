'use client'

import { useCallback, useEffect, useMemo, useState, useRef } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { useAISettings, type ResponseStyle } from '@/contexts/AISettingsContext'
import {
  CommandPalette,
  type CommandPaletteSection,
  type CommandPaletteItem,
} from '@/components/CommandPalette'
import { NotificationsPanel } from '@/components/layout/NotificationsPanel'

const nav = [
  { href: '/dashboard', label: 'Home' },
  { href: '/dashboard/documents', label: 'Documents' },
  { href: '/dashboard/questionnaires', label: 'Questionnaires' },
  { href: '/dashboard/review', label: 'Review' },
  { href: '/dashboard/requests', label: 'Requests' },
  { href: '/dashboard/exports', label: 'Exports' },
]

const sidebarOnlyRoutes = [
  { href: '/dashboard/compliance-gaps', label: 'Coverage' },
  { href: '/dashboard/trust-center', label: 'Trust Center' },
  { href: '/dashboard/members', label: 'Members' },
  { href: '/dashboard/notifications', label: 'Alerts / Notifications' },
  { href: '/dashboard/slack', label: 'Slack' },
  { href: '/dashboard/gmail', label: 'Gmail' },
  { href: '/dashboard/audit', label: 'Activity' },
  { href: '/dashboard/ai-governance', label: 'AI Insights' },
  { href: '/dashboard/settings', label: 'Settings' },
  { href: '/dashboard/security', label: 'Account Security' },
]

function initials(displayName: string | null, email: string): string {
  if (displayName?.trim()) {
    const parts = displayName.trim().split(/\s+/)
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase().slice(0, 2)
    return displayName.slice(0, 2).toUpperCase()
  }
  const local = email.split('@')[0]
  return local ? local.slice(0, 2).toUpperCase() : '?'
}

const SEARCH_DEBOUNCE_MS = 250
const NAV_PLACEHOLDER = '__nav_pick__'

const AI_MODEL_OPTIONS = [
  { value: 'gpt-4o-mini', label: 'gpt-4o-mini (default)' },
  { value: 'gpt-4o', label: 'gpt-4o' },
  { value: 'gpt-4.1-mini', label: 'gpt-4.1-mini' },
]
const RESPONSE_STYLES: { value: ResponseStyle; label: string; temperature: number }[] = [
  { value: 'precise', label: 'Precise', temperature: 0.2 },
  { value: 'balanced', label: 'Balanced', temperature: 0.35 },
  { value: 'natural', label: 'Natural', temperature: 0.5 },
]

const topbarNavRoutes = [...nav, ...sidebarOnlyRoutes]

export function Topbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { user, workspace, permissions } = useAuth()
  const isAdmin = permissions.can_admin
  const { model: aiModel, responseStyle, setModel: setAiModel, setResponseStyle, loadFromWorkspace } = useAISettings()

  const [paletteOpen, setPaletteOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [searchDocs, setSearchDocs] = useState<{ id: number; filename: string }[]>([])
  const [searchQnrs, setSearchQnrs] = useState<{ id: number; filename: string }[]>([])
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)
  const notificationsAnchorRef = useRef<HTMLDivElement>(null)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const [aiSaving, setAiSaving] = useState(false)
  const [automateEverything, setAutomateEverything] = useState(false)

  const matchedNavHref = useMemo(() => {
    return topbarNavRoutes.find(
      ({ href }) => pathname === href || (href !== '/dashboard' && pathname.startsWith(href))
    )?.href
  }, [pathname])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        if (pathname?.startsWith('/dashboard')) setPaletteOpen(true)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [pathname])

  const fetchUnread = useCallback(() => {
    fetch('/api/in-app-notifications/unread-count', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : { count: 0 }))
      .then((d) => setUnreadCount(d.count || 0))
      .catch(() => setUnreadCount(0))
  }, [])

  useEffect(() => {
    if (!pathname?.startsWith('/dashboard')) return
    fetchUnread()
  }, [pathname, fetchUnread])

  useEffect(() => {
    if (!pathname?.startsWith('/dashboard')) return
    const id = setInterval(fetchUnread, 30_000)
    return () => clearInterval(id)
  }, [pathname, fetchUnread])

  useEffect(() => {
    if (!paletteOpen) return
    setQuery('')
    setSearchDocs([])
    setSearchQnrs([])
  }, [paletteOpen])

  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    const q = query.trim()
    const workspaceId = workspace?.id
    if (q.length < 2 || workspaceId == null) {
      setSearchDocs([])
      setSearchQnrs([])
      return
    }
    searchDebounceRef.current = setTimeout(async () => {
      try {
        const [docsRes, qnrsRes] = await Promise.all([
          fetch(`/api/documents/?workspace_id=${workspaceId}&q=${encodeURIComponent(q)}`, { credentials: 'include' }),
          fetch(`/api/questionnaires/?workspace_id=${workspaceId}&q=${encodeURIComponent(q)}`, { credentials: 'include' }),
        ])
        const docs = docsRes.ok ? await docsRes.json() : []
        const qnrs = qnrsRes.ok ? await qnrsRes.json() : []
        setSearchDocs(Array.isArray(docs) ? docs : [])
        setSearchQnrs(Array.isArray(qnrs) ? qnrs : [])
      } catch {
        setSearchDocs([])
        setSearchQnrs([])
      }
      searchDebounceRef.current = null
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    }
  }, [query, workspace?.id])

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  // Load admin settings when menu opens
  useEffect(() => {
    if (!menuOpen || !isAdmin) return
    loadFromWorkspace()
    fetch('/api/workspaces/current', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setAutomateEverything(!!d.ai_automate_everything) })
      .catch(() => {})
  }, [menuOpen, isAdmin, loadFromWorkspace])

  const navigateAndClose = useCallback(
    (href: string) => {
      router.push(href)
      setPaletteOpen(false)
    },
    [router]
  )

  const logout = useCallback(async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setPaletteOpen(false)
    setMenuOpen(false)
    router.push('/login')
    router.refresh()
  }, [router])

  const saveAiSettings = async () => {
    if (!isAdmin) return
    setAiSaving(true)
    try {
      const styleConfig = RESPONSE_STYLES.find((s) => s.value === responseStyle)
      const temperature = styleConfig?.temperature ?? 0.35
      const modelValue = aiModel && AI_MODEL_OPTIONS.some((m) => m.value === aiModel) ? aiModel : null
      await fetch('/api/workspaces/current', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ ai_completion_model: modelValue, ai_temperature: temperature }),
      })
    } finally { setAiSaving(false) }
  }

  const toggleAutomate = async () => {
    const next = !automateEverything
    setAutomateEverything(next)
    try {
      const r = await fetch('/api/workspaces/current', {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ai_automate_everything: next }),
      })
      if (!r.ok) setAutomateEverything(!next)
    } catch { setAutomateEverything(!next) }
  }

  const paletteSections = useMemo((): CommandPaletteSection[] => {
    const qLower = query.trim().toLowerCase()
    const jumpItems: CommandPaletteItem[] = [
      ...nav,
      ...sidebarOnlyRoutes,
    ]
      .filter((r) => !qLower || r.label.toLowerCase().includes(qLower))
      .map((r) => ({
        id: `nav-${r.href}`,
        label: r.label,
        onSelect: () => navigateAndClose(r.href),
      }))
    const sections: CommandPaletteSection[] = []
    if (jumpItems.length > 0) {
      sections.push({ title: 'Jump to', items: jumpItems })
    }
    if (searchDocs.length > 0) {
      sections.push({
        title: 'Documents',
        items: searchDocs.map((d) => ({
          id: `doc-${d.id}`,
          label: d.filename || `Document ${d.id}`,
          onSelect: () => navigateAndClose('/dashboard/documents'),
        })),
      })
    }
    if (searchQnrs.length > 0) {
      sections.push({
        title: 'Questionnaires',
        items: searchQnrs.map((qnr) => ({
          id: `qnr-${qnr.id}`,
          label: qnr.filename || `Questionnaire ${qnr.id}`,
          onSelect: () => navigateAndClose(`/dashboard/review/${qnr.id}`),
        })),
      })
    }
    const actionItems: CommandPaletteItem[] = [
      { id: 'action-upload-doc', label: 'Upload document', onSelect: () => navigateAndClose('/dashboard/documents') },
      { id: 'action-upload-qnr', label: 'Upload questionnaire', onSelect: () => navigateAndClose('/dashboard/questionnaires') },
      { id: 'action-create-workspace', label: 'Create workspace', onSelect: () => navigateAndClose('/dashboard/settings') },
      { id: 'action-signout', label: 'Sign out', onSelect: logout },
    ]
    if (!qLower || actionItems.some((a) => a.label.toLowerCase().includes(qLower))) {
      sections.push({ title: 'Actions', items: actionItems })
    }
    return sections
  }, [query, searchDocs, searchQnrs, navigateAndClose, logout])

  const userEmail = user?.email ?? ''
  const userName = user?.display_name || userEmail.split('@')[0] || 'User'
  const userRole = isAdmin ? 'Admin' : 'Member'

  return (
    <header
      className="flex w-full min-w-0 flex-col gap-3 px-4 py-3 sm:px-5 sm:py-4 lg:flex-row lg:items-center lg:justify-between lg:gap-4 xl:px-7"
      style={{
        background: 'rgba(7, 13, 24, 0.72)',
        backdropFilter: 'blur(18px)',
        borderBottom: '1px solid var(--tc-border)',
        position: 'relative',
        zIndex: 30,
      }}
    >
      <div className="flex min-w-0 w-full max-w-full flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
        <Link
          href="/dashboard"
          className="flex shrink-0 items-center gap-2 font-bold tracking-tight text-[var(--tc-text)] sm:gap-3"
        >
          <div
            className="grid h-9 w-9 place-items-center rounded-xl text-lg"
            style={{
              background: 'linear-gradient(135deg, #7c96ff, #5b7cff 55%, #2dd4bf)',
              boxShadow: '0 12px 30px rgba(91,124,255,0.35)',
            }}
          >
            ✓
          </div>
          <span className="truncate text-[15px] sm:text-base">Trust Copilot</span>
        </Link>
        <nav
          className="hidden min-w-0 flex-1 flex-wrap items-center gap-1 lg:flex"
          aria-label="Primary"
        >
          {nav.map(({ href, label }) => {
            const active = pathname === href || (href !== '/dashboard' && pathname.startsWith(href))
            return (
              <Link
                key={href}
                href={href}
                scroll={false}
                prefetch={true}
                className={`whitespace-nowrap rounded-xl px-3 py-2 text-sm transition-all duration-150 ${
                  active
                    ? 'bg-white/5 text-[var(--tc-text)]'
                    : 'text-[var(--tc-muted)] hover:bg-white/5 hover:text-[var(--tc-text)]'
                }`}
              >
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="min-w-0 lg:hidden sm:min-w-[11rem]">
          <label htmlFor="dashboard-primary-nav" className="sr-only">
            Primary navigation
          </label>
          <select
            id="dashboard-primary-nav"
            key={pathname}
            className="w-full min-w-0 cursor-pointer rounded-xl border border-[var(--tc-border)] bg-white/5 py-2 pl-3 pr-8 text-sm text-[var(--tc-text)] focus:border-[var(--tc-soft)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-soft)]"
            style={{ colorScheme: 'dark', accentColor: 'var(--tc-primary)' }}
            value={matchedNavHref ?? NAV_PLACEHOLDER}
            onChange={(e) => {
              const v = e.target.value
              if (v && v !== NAV_PLACEHOLDER) router.push(v)
            }}
          >
            {!matchedNavHref && (
              <option value={NAV_PLACEHOLDER} disabled>
                Jump to page...
              </option>
            )}
            <optgroup label="Main">
              {nav.map(({ href, label }) => (
                <option key={href} value={href}>
                  {label}
                </option>
              ))}
            </optgroup>
            <optgroup label="More">
              {sidebarOnlyRoutes.map(({ href, label }) => (
                <option key={href} value={href}>
                  {label}
                </option>
              ))}
            </optgroup>
          </select>
        </div>
      </div>

      <div className="flex w-full max-w-full min-w-0 shrink-0 flex-wrap items-center justify-start gap-2 sm:w-auto sm:justify-end sm:gap-3 lg:justify-end">
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="flex min-w-0 max-w-full cursor-pointer items-center justify-between gap-2 rounded-xl border border-[var(--tc-border)] bg-white/5 px-2.5 py-2 text-sm text-[var(--tc-muted)] hover:bg-white/10 sm:min-w-[10rem] sm:gap-3 sm:px-3.5 sm:py-2.5 md:min-w-[12rem] lg:min-w-[14rem] xl:min-w-[190px]"
          title="Search or jump (Ctrl+K)"
        >
          <span className="truncate">
            <span className="sm:hidden">Search...</span>
            <span className="hidden sm:inline">Ctrl+K Search or jump</span>
          </span>
          <span className="shrink-0">↵</span>
        </button>
        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          sections={paletteSections}
          query={query}
          onQueryChange={setQuery}
          placeholder="Search or jump to action..."
        />

        <div className="relative" ref={notificationsAnchorRef}>
          <button
            type="button"
            onClick={() => setNotificationsOpen((o) => !o)}
            className="relative grid h-10 w-10 place-items-center rounded-full border border-[var(--tc-border)] bg-white/5 transition hover:bg-white/10"
            aria-label="Notifications"
            aria-expanded={notificationsOpen}
          >
            🔔
            {unreadCount > 0 && (
              <span
                className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white"
                style={{ background: 'var(--tc-danger)' }}
              >
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>
          <NotificationsPanel
            open={notificationsOpen}
            onClose={() => setNotificationsOpen(false)}
            onUnreadCountChange={setUnreadCount}
            anchorRef={notificationsAnchorRef}
          />
        </div>

        {/* ── Account Menu ── */}
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            className="grid h-10 w-10 place-items-center rounded-full font-bold text-white transition hover:opacity-90"
            style={{
              background: 'linear-gradient(135deg, rgba(124,150,255,0.35), rgba(45,212,191,0.15))',
              border: `1px solid ${menuOpen ? 'rgba(91,124,255,0.5)' : 'var(--tc-border)'}`,
            }}
            title="Account menu"
            aria-expanded={menuOpen}
            aria-haspopup="true"
          >
            {user ? initials(user.display_name, user.email) : '—'}
          </button>

          {menuOpen && (
            <div
              className="absolute right-0 top-full z-50 mt-2 w-72 rounded-xl border border-[var(--tc-border)] shadow-2xl overflow-hidden"
              style={{ background: 'rgba(12, 18, 32, 0.98)', backdropFilter: 'blur(24px)' }}
            >
              {/* Header */}
              <div className="px-4 py-3 border-b border-white/5">
                <div className="flex items-center gap-3">
                  <div
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full font-bold text-sm text-white"
                    style={{ background: 'linear-gradient(135deg, rgba(124,150,255,0.4), rgba(45,212,191,0.2))' }}
                  >
                    {user ? initials(user.display_name, user.email) : '—'}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-[var(--tc-text)] truncate">{userName}</div>
                    <div className="text-[11px] text-[var(--tc-muted)] truncate">{userEmail}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <span className="inline-flex items-center rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-[var(--tc-muted)]">
                    {userRole}
                  </span>
                  {workspace && (
                    <span className="text-[10px] text-[var(--tc-muted)] truncate">
                      {workspace.name}
                    </span>
                  )}
                </div>
              </div>

              {/* Personal Actions */}
              <div className="py-1">
                <MenuLink href="/dashboard/security" label="Account Security" icon="🔐" onClick={() => setMenuOpen(false)} />
                <MenuLink href="/dashboard/security" label="Change Password" icon="🔑" onClick={() => setMenuOpen(false)} />
                <MenuButton label="Sign Out" icon="🚪" onClick={logout} danger />
              </div>

              {/* Admin AI Settings */}
              {isAdmin && (
                <>
                  <div className="border-t border-white/5" />
                  <div className="px-4 py-3">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-[var(--tc-muted)] mb-2">
                      AI Settings
                    </div>
                    <div className="space-y-2">
                      <MenuSelect
                        label="Model"
                        value={AI_MODEL_OPTIONS.some((m) => m.value === aiModel) ? aiModel : 'gpt-4o-mini'}
                        options={AI_MODEL_OPTIONS}
                        onChange={(v) => setAiModel(v || 'gpt-4o-mini')}
                      />
                      <MenuSelect
                        label="Response Style"
                        value={responseStyle}
                        options={RESPONSE_STYLES.map((s) => ({ value: s.value, label: s.label }))}
                        onChange={(v) => setResponseStyle(v as ResponseStyle)}
                      />
                      <button
                        type="button"
                        onClick={saveAiSettings}
                        disabled={aiSaving}
                        className="w-full rounded-lg border border-white/10 bg-white/5 py-1.5 text-[11px] font-medium text-[var(--tc-text)] hover:bg-white/10 disabled:opacity-50 transition-colors"
                      >
                        {aiSaving ? 'Saving...' : 'Save for workspace'}
                      </button>
                    </div>

                    <div className="mt-3 pt-3 border-t border-white/5">
                      <label className="flex items-center gap-2.5 cursor-pointer">
                        <div
                          className={`relative w-8 h-[18px] rounded-full transition-colors ${automateEverything ? 'bg-[rgba(91,124,255,0.5)]' : 'bg-white/10'}`}
                          onClick={toggleAutomate}
                        >
                          <div className={`absolute top-[2px] left-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform ${automateEverything ? 'translate-x-[14px]' : ''}`} />
                        </div>
                        <div>
                          <span className="text-[11px] font-medium text-[var(--tc-text)]">Automate everything</span>
                          <span className="block text-[10px] text-[var(--tc-muted)] leading-tight">
                            Auto-generate answers on upload
                          </span>
                        </div>
                      </label>
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

/* ── Menu sub-components ── */

function MenuLink({ href, label, icon, onClick }: { href: string; label: string; icon: string; onClick: () => void }) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className="flex items-center gap-2.5 px-4 py-2 text-[13px] text-[var(--tc-text)] hover:bg-white/5 transition-colors"
    >
      <span className="text-sm w-5 text-center">{icon}</span>
      {label}
    </Link>
  )
}

function MenuButton({ label, icon, onClick, danger }: { label: string; icon: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 px-4 py-2 text-[13px] transition-colors ${
        danger ? 'text-red-400 hover:bg-red-500/10' : 'text-[var(--tc-text)] hover:bg-white/5'
      }`}
    >
      <span className="text-sm w-5 text-center">{icon}</span>
      {label}
    </button>
  )
}

function MenuSelect({ label, value, options, onChange }: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="block text-[10px] font-medium text-[var(--tc-muted)] mb-0.5">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-[var(--tc-text)] focus:border-[var(--tc-soft)] focus:outline-none"
        style={{ colorScheme: 'dark' }}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  )
}
