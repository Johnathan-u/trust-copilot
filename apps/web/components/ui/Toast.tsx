'use client'

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { subscribeToastRegion, toastPortalTarget } from '@/lib/render-state'
import {
  autoDismissMs,
  persistentToastRegions,
  toastRegionId,
  TOAST_LIVE_ROOT_ID,
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
 * Visual toast. Its text is portaled into the one live region for that
 * politeness. The region is mounted by `ToastLiveRegions` before any text
 * exists. The region node is read from the document with a server snapshot
 * of null, so the first render does not disagree with the server.
 * `aria-atomic` sits on this card. The region keeps `aria-live`, and a new
 * card is the change that gets announced. Atomic on the card keeps a second
 * toast in the same region from being read again as part of that change.
 * This component does not move focus. Callers should not start a second timer.
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

  const regionId = toastRegionId(type)
  const region = useSyncExternalStore(
    subscribeToastRegion,
    () => toastPortalTarget(false, document.getElementById(regionId)),
    () => toastPortalTarget(true, null)
  )

  const icon = tone[type]
  const card = (
    <div
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

  if (!region) return null
  return createPortal(card, region)
}

/**
 * Always mounted. Both regions are in the DOM with no toast text. `Toast`
 * inserts a card into one of them later.
 */
export function ToastLiveRegions() {
  return (
    <div
      id={TOAST_LIVE_ROOT_ID}
      className="pointer-events-none fixed inset-x-tc-4 bottom-tc-4 z-40 flex flex-col items-stretch sm:left-auto sm:right-tc-6 sm:w-[min(360px,calc(100vw-2rem))]"
    >
      {persistentToastRegions().map((region) => (
        <div
          key={region.id}
          id={region.id}
          role={region.role}
          aria-live={region.ariaLive}
          className="flex flex-col gap-tc-2"
        />
      ))}
    </div>
  )
}

/** Toasts portal into `ToastLiveRegions`, so this only keeps the call-site grouping. */
export function ToastViewport({ children }: { children: ReactNode }) {
  return <>{children}</>
}

export function ToastNotice(props: ToastProps) {
  return (
    <ToastViewport>
      <Toast {...props} />
    </ToastViewport>
  )
}
