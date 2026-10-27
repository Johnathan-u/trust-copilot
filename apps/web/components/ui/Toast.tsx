'use client'

import { useEffect, useRef, type ReactNode } from 'react'
import {
  autoDismissMs,
  liveRegionForSeverity,
  type ToastSeverity,
} from '@/lib/toast'

export interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastProps {
  title: string
  message: string
  type?: ToastSeverity
  onDismiss?: () => void
  /** Extra control such as Undo, View or Retry. Presence cancels auto-dismiss. */
  action?: ToastAction
}

const tone: Record<ToastSeverity, { bg: string; fg: string; glyph: string }> = {
  success: {
    bg: 'var(--tc-success-surface)',
    fg: 'var(--tc-success)',
    glyph: '✓',
  },
  info: { bg: 'var(--tc-info-surface)', fg: 'var(--tc-info)', glyph: 'i' },
  warning: {
    bg: 'var(--tc-warning-surface)',
    fg: 'var(--tc-warning)',
    glyph: '!',
  },
  error: { bg: 'var(--tc-danger-surface)', fg: 'var(--tc-danger)', glyph: '!' },
}

/**
 * One announcement. Success, info and warning leave after 4000ms. Errors, and
 * any toast with an action button, stay until dismiss. This component does not
 * move focus. Callers should not start a second dismiss timer.
 */
export function Toast({
  title,
  message,
  type = 'success',
  onDismiss,
  action,
}: ToastProps) {
  const onDismissRef = useRef(onDismiss)
  useEffect(() => {
    onDismissRef.current = onDismiss
  }, [onDismiss])
  const hasAction = action != null

  useEffect(() => {
    const ms = autoDismissMs(type, { hasAction })
    if (ms == null) return
    const id = window.setTimeout(() => onDismissRef.current?.(), ms)
    return () => window.clearTimeout(id)
  }, [title, message, type, hasAction])

  const icon = tone[type]
  const live = liveRegionForSeverity(type)
  return (
    <div
      role={live.role}
      aria-live={live.ariaLive}
      aria-atomic="true"
      className="tc-toast pointer-events-auto relative flex w-full min-w-0 max-w-[360px] gap-tc-3 rounded-tc-sm border border-tc-border-strong p-tc-4 pr-tc-8 shadow-[var(--tc-shadow)]"
      style={{ background: 'var(--tc-surface-overlay)' }}
    >
      <div
        className="flex h-9 w-9 flex-shrink-0 place-items-center rounded-tc-xs text-tc-label font-bold"
        style={{ background: icon.bg, color: icon.fg }}
        aria-hidden="true"
      >
        {icon.glyph}
      </div>
      <div className="min-w-0">
        <strong className="block text-tc-label text-tc-text">{title}</strong>
        <span className="mt-tc-1 block text-tc-caption text-tc-muted">
          {message}
        </span>
        {action ? (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-tc-2 inline-flex min-h-tc-6 items-center rounded-tc-xs px-tc-2 text-tc-label font-semibold text-tc-primary hover:bg-[var(--tc-hover)]"
          >
            {action.label}
          </button>
        ) : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="absolute right-tc-2 top-tc-2 inline-flex min-h-tc-6 min-w-tc-6 items-center justify-center rounded-tc-xs p-tc-1 text-tc-muted hover:bg-[var(--tc-hover)] hover:text-tc-text"
          aria-label={`Dismiss ${title}`}
        >
          ×
        </button>
      ) : null}
    </div>
  )
}

/** Fixed stack. Toasts stay in normal flow so several can be read and dismissed. */
export function ToastViewport({ children }: { children: ReactNode }) {
  return (
    <div className="pointer-events-none fixed inset-x-tc-4 bottom-tc-4 z-40 flex flex-col items-stretch gap-tc-2 sm:left-auto sm:right-tc-6 sm:w-[min(360px,calc(100vw-2rem))]">
      {children}
    </div>
  )
}

export function ToastNotice(props: ToastProps) {
  return (
    <ToastViewport>
      <Toast {...props} />
    </ToastViewport>
  )
}
