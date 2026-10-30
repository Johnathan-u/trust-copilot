'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import Link from 'next/link'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { failureOf, isAbortError, readSectionJson } from '@/lib/section-load'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'

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
export type Alert = {
  id: number
  action: string
  occurred_at: string | null
  details: string | null
}

const CATEGORY_STYLES: Record<
  string,
  { bg: string; text: string; label: string }
> = {
  info: {
    bg: 'rgba(91,124,255,0.12)',
    text: 'rgb(140,165,255)',
    label: 'Info',
  },
  admin: {
    bg: 'rgba(168,85,247,0.12)',
    text: 'rgb(192,132,252)',
    label: 'Admin',
  },
  warning: {
    bg: 'rgba(245,158,11,0.12)',
    text: 'rgb(251,191,36)',
    label: 'Warning',
  },
  error: {
    bg: 'rgba(239,68,68,0.12)',
    text: 'rgb(248,113,113)',
    label: 'Error',
  },
  success: {
    bg: 'rgba(34,197,94,0.12)',
    text: 'rgb(74,222,128)',
    label: 'Success',
  },
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
  /** Id of this panel. The bell sets aria-controls to the same value. */
  panelId: string
  // Legacy props kept for compat but no longer used
  alerts?: Alert[]
  loading?: boolean
}

function focusTrigger(anchor: HTMLElement | null) {
  anchor?.querySelector<HTMLButtonElement>('button')?.focus()
}

/**
 * Disclosure popover. Not a dialog: no focus trap, no inert background,
 * no aria-modal. Escape and a pointer event outside the anchor close it
 * and return focus to the bell button.
 */
export function NotificationsPanel({
  open,
  onClose,
  onUnreadCountChange,
  anchorRef,
  panelId,
}: NotificationsPanelProps) {
  const titleId = useId()
  const descriptionId = useId()
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])
  const [notifications, setNotifications] = useState<InAppNotification[]>([])
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState<ApiFailurePresentation | null>(null)
  const [actionFailure, setActionFailure] =
    useState<ApiFailurePresentation | null>(null)
  const [unreadCount, setUnreadCount] = useState<number | null>(null)
  const [loadId, setLoadId] = useState(0)
  const unreadRequest = useRef(0)

  const refreshUnreadCount = useCallback(
    async (signal?: AbortSignal) => {
      const request = ++unreadRequest.current
      const data = await readSectionJson(
        await fetch('/api/in-app-notifications/unread-count', {
          credentials: 'include',
          signal,
        })
      )
      const count =
        data && typeof data === 'object'
          ? (data as { count?: unknown }).count
          : null
      if (
        typeof count !== 'number' ||
        !Number.isSafeInteger(count) ||
        count < 0
      ) {
        throw new Error('malformed')
      }
      if (signal?.aborted || request !== unreadRequest.current) return
      setUnreadCount(count)
      onUnreadCountChange?.(count)
    },
    [onUnreadCountChange]
  )

  const fetchNotifications = useCallback(() => {
    const controller = new AbortController()
    fetch('/api/in-app-notifications?limit=20', {
      credentials: 'include',
      signal: controller.signal,
    })
      .then((response) => readSectionJson(response))
      .then(async (data) => {
        const record =
          data && typeof data === 'object'
            ? (data as { notifications?: unknown })
            : {}
        const rows = Array.isArray(record.notifications)
          ? (record.notifications as InAppNotification[])
          : null
        if (!rows) {
          throw new Error('malformed')
        }
        if (controller.signal.aborted) return
        setNotifications(rows)
        await refreshUnreadCount(controller.signal)
        if (controller.signal.aborted) return
        setFailure(null)
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        setNotifications([])
        setFailure(failureOf(error))
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [refreshUnreadCount])

  const reloadNotifications = useCallback(() => {
    setLoading(true)
    setFailure(null)
    setActionFailure(null)
    setLoadId((value) => value + 1)
    return fetchNotifications()
  }, [fetchNotifications])

  const panelKey = useKeyedGeneration(open ? 'open' : 'closed', {
    runOnMount: false,
  })
  if (panelKey.changed && open) {
    setLoading(true)
    setFailure(null)
    setLoadId(panelKey.generation)
  }

  useEffect(() => {
    if (!open) return
    return fetchNotifications()
  }, [open, fetchNotifications])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      const anchor = anchorRef.current
      const target = event.target
      if (anchor && target instanceof Node && anchor.contains(target)) return
      onCloseRef.current()
      window.setTimeout(() => focusTrigger(anchorRef.current), 0)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onCloseRef.current()
      focusTrigger(anchorRef.current)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, anchorRef])

  const markRead = async (id: number) => {
    setActionFailure(null)
    try {
      await readSectionJson(
        await fetch(`/api/in-app-notifications/${id}/read`, {
          method: 'POST',
          credentials: 'include',
        })
      )
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      await refreshUnreadCount()
    } catch (error) {
      setActionFailure(failureOf(error))
    }
  }

  const markAllRead = async () => {
    setActionFailure(null)
    try {
      await readSectionJson(
        await fetch('/api/in-app-notifications/read-all', {
          method: 'POST',
          credentials: 'include',
        })
      )
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      await refreshUnreadCount()
    } catch (error) {
      setActionFailure(failureOf(error))
    }
  }

  if (!open) return null

  return (
    <div
      id={panelId}
      className="absolute right-0 top-full z-50 mt-2 w-[min(400px,92vw)] overflow-hidden rounded-xl border border-[var(--tc-border)] shadow-[var(--tc-shadow)]"
      style={{ background: 'var(--tc-surface-overlay)' }}
    >
      <div className="flex items-start justify-between gap-tc-2 border-b border-[var(--tc-border)] px-4 py-3">
        <div>
          <h3
            id={titleId}
            className="text-sm font-semibold text-[var(--tc-text)]"
          >
            Notifications
          </h3>
          <p
            id={descriptionId}
            className="mt-0.5 text-xs text-[var(--tc-muted)]"
          >
            {unreadCount === null
              ? 'Unread count unavailable'
              : unreadCount > 0
                ? `${unreadCount} unread`
                : 'All caught up'}
          </p>
        </div>
        <div className="flex items-center gap-tc-2">
          {unreadCount !== null && unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              className="text-xs text-[var(--tc-soft)] hover:text-[var(--tc-text)] transition"
            >
              Mark all read
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              onClose()
              focusTrigger(anchorRef.current)
            }}
            className="inline-flex min-h-tc-6 min-w-tc-6 items-center justify-center rounded-tc-xs text-tc-muted hover:bg-[var(--tc-hover)] hover:text-tc-text"
            aria-label="Close notifications"
          >
            ×
          </button>
        </div>
      </div>

      <div className="max-h-[min(400px,65vh)] overflow-y-auto">
        {actionFailure && (
          <div className="p-tc-4">
            <ErrorState failure={actionFailure} onRetry={reloadNotifications} />
          </div>
        )}
        {loading ? (
          <LoadingState
            label="Loading notifications"
            onRetry={reloadNotifications}
            resetKey={loadId}
          >
            <p className="px-4 py-8 text-center text-tc-label text-tc-muted">
              Loading notifications
            </p>
          </LoadingState>
        ) : failure ? (
          <div className="p-tc-4">
            <ErrorState failure={failure} onRetry={reloadNotifications} />
          </div>
        ) : notifications.length === 0 ? (
          <EmptyState
            title="No notifications"
            description="Nothing new is waiting in this account."
            action={
              <Link
                href="/dashboard/notifications"
                className="inline-flex min-h-tc-8 items-center justify-center rounded-tc-sm border border-tc-border-strong bg-tc-surface-raised px-tc-4 text-tc-label font-semibold text-tc-text"
              >
                Open notifications
              </Link>
            }
          />
        ) : (
          <ul>
            {notifications.map((n) => {
              const style = CATEGORY_STYLES[n.category] || CATEGORY_STYLES.info
              const content = (
                <div
                  className={`px-4 py-3 transition ${!n.is_read ? 'bg-white/[0.03]' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <div
                      className={`mt-0.5 flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold`}
                      style={{ background: style.bg, color: style.text }}
                    >
                      {style.label}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div
                        className={`text-sm ${!n.is_read ? 'font-medium text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}
                      >
                        {n.title}
                      </div>
                      {n.body && (
                        <div className="mt-0.5 text-xs text-[var(--tc-muted)] line-clamp-2">
                          {n.body}
                        </div>
                      )}
                      <div className="mt-1 text-[11px] text-[var(--tc-muted)]">
                        {formatTime(n.created_at)}
                      </div>
                    </div>
                    {!n.is_read && (
                      <div
                        className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-[var(--tc-primary)]"
                        title="Unread"
                      />
                    )}
                  </div>
                </div>
              )
              return (
                <li
                  key={n.id}
                  className="border-b border-white/5 last:border-0 cursor-pointer hover:bg-white/[0.02]"
                  onClick={() => {
                    if (!n.is_read) markRead(n.id)
                  }}
                >
                  {n.link ? (
                    <Link href={n.link} onClick={onClose}>
                      {content}
                    </Link>
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
