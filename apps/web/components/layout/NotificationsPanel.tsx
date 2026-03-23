'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'

export type InAppNotification = {
  id: number
  title: string
  body: string | null
  category: string
  link: string | null
  is_read: boolean
  admin_only: boolean
  created_at: string | null
}

// Keep the old Alert type for backward compat (security alerts still work)
export type Alert = { id: number; action: string; occurred_at: string | null; details: string | null }

const CATEGORY_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  info:     { bg: 'rgba(91,124,255,0.12)', text: 'rgb(140,165,255)', label: 'Info' },
  admin:    { bg: 'rgba(168,85,247,0.12)',  text: 'rgb(192,132,252)', label: 'Admin' },
  warning:  { bg: 'rgba(245,158,11,0.12)',  text: 'rgb(251,191,36)',  label: 'Warning' },
  error:    { bg: 'rgba(239,68,68,0.12)',   text: 'rgb(248,113,113)', label: 'Error' },
  success:  { bg: 'rgba(34,197,94,0.12)',   text: 'rgb(74,222,128)',  label: 'Success' },
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return 'just now'
    if (diffMin < 60) return `${diffMin}m ago`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h ago`
    const diffDay = Math.floor(diffHr / 24)
    if (diffDay < 7) return `${diffDay}d ago`
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

interface NotificationsPanelProps {
  open: boolean
  onClose: () => void
  onUnreadCountChange?: (count: number) => void
  anchorRef: React.RefObject<HTMLDivElement | null>
  // Legacy props kept for compat but no longer used
  alerts?: Alert[]
  loading?: boolean
}

export function NotificationsPanel({ open, onClose, onUnreadCountChange, anchorRef }: NotificationsPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [notifications, setNotifications] = useState<InAppNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  const fetchNotifications = useCallback(() => {
    setLoading(true)
    setError(false)
    fetch('/api/in-app-notifications?limit=20', { credentials: 'include' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        setNotifications(d.notifications ?? [])
        const unread = (d.notifications ?? []).filter((n: InAppNotification) => !n.is_read).length
        onUnreadCountChange?.(unread)
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [onUnreadCountChange])

  useEffect(() => {
    if (open) fetchNotifications()
  }, [open, fetchNotifications])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const anchor = anchorRef.current
      const panel = panelRef.current
      const target = e.target as Node
      if (anchor?.contains(target) || panel?.contains(target)) return
      onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open, onClose, anchorRef])

  const markRead = async (id: number) => {
    await fetch(`/api/in-app-notifications/${id}/read`, { method: 'POST', credentials: 'include' })
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
    onUnreadCountChange?.(notifications.filter(n => !n.is_read && n.id !== id).length)
  }

  const markAllRead = async () => {
    await fetch('/api/in-app-notifications/read-all', { method: 'POST', credentials: 'include' })
    setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
    onUnreadCountChange?.(0)
  }

  if (!open) return null

  const unreadCount = notifications.filter(n => !n.is_read).length

  return (
    <div
      ref={panelRef}
      className="absolute right-0 top-full z-20 mt-2 w-[min(400px,92vw)] rounded-xl border border-[var(--tc-border)] shadow-[var(--tc-shadow)] overflow-hidden"
      style={{ background: 'var(--tc-panel)' }}
      role="dialog"
      aria-modal="true"
      aria-label="Notifications"
    >
      <div className="flex items-center justify-between border-b border-[var(--tc-border)] px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--tc-text)]">Notifications</h3>
          <p className="mt-0.5 text-xs text-[var(--tc-muted)]">
            {unreadCount > 0 ? `${unreadCount} unread` : 'All caught up'}
          </p>
        </div>
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={markAllRead}
            className="text-xs text-[var(--tc-soft)] hover:text-[var(--tc-text)] transition"
          >
            Mark all read
          </button>
        )}
      </div>

      <div className="max-h-[min(400px,65vh)] overflow-y-auto">
        {loading ? (
          <div className="px-4 py-8 text-center text-sm text-[var(--tc-muted)]">Loading...</div>
        ) : error ? (
          <div className="px-4 py-8 text-center text-sm text-red-400">Failed to load notifications</div>
        ) : notifications.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <div className="text-2xl mb-2 opacity-40">🔔</div>
            <div className="text-sm text-[var(--tc-muted)]">No notifications</div>
          </div>
        ) : (
          <ul>
            {notifications.map(n => {
              const style = CATEGORY_STYLES[n.category] || CATEGORY_STYLES.info
              const content = (
                <div className={`px-4 py-3 transition ${!n.is_read ? 'bg-white/[0.03]' : ''}`}>
                  <div className="flex items-start gap-2">
                    <div className={`mt-0.5 flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold`} style={{ background: style.bg, color: style.text }}>
                      {style.label}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className={`text-sm ${!n.is_read ? 'font-medium text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>
                        {n.title}
                      </div>
                      {n.body && (
                        <div className="mt-0.5 text-xs text-[var(--tc-muted)] line-clamp-2">{n.body}</div>
                      )}
                      <div className="mt-1 text-[11px] text-[var(--tc-muted)]">{formatTime(n.created_at)}</div>
                    </div>
                    {!n.is_read && (
                      <div className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-[var(--tc-primary)]" title="Unread" />
                    )}
                  </div>
                </div>
              )
              return (
                <li key={n.id} className="border-b border-white/5 last:border-0 cursor-pointer hover:bg-white/[0.02]"
                    onClick={() => { if (!n.is_read) markRead(n.id) }}>
                  {n.link ? (
                    <Link href={n.link} onClick={onClose}>{content}</Link>
                  ) : (
                    content
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-[var(--tc-border)] px-4 py-2.5 flex items-center justify-between">
        <Link
          href="/dashboard/audit"
          className="text-xs text-[var(--tc-soft)] hover:text-[var(--tc-text)]"
          onClick={onClose}
        >
          View audit log
        </Link>
        <Link
          href="/dashboard/notifications"
          className="text-xs text-[var(--tc-soft)] hover:text-[var(--tc-text)]"
          onClick={onClose}
        >
          Notification settings
        </Link>
      </div>
    </div>
  )
}
