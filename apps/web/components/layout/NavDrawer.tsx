'use client'

import { useEffect, useRef } from 'react'
import { APP_NAV_DOCK_MEDIA } from '@/lib/app-navigation'
import { Sidebar } from './Sidebar'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'

function focusableIn(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => {
    if (el.closest('[hidden]')) return false
    if (el.getAttribute('aria-hidden') === 'true') return false
    const style = window.getComputedStyle(el)
    return style.display !== 'none' && style.visibility !== 'hidden'
  })
}

interface NavDrawerProps {
  open: boolean
  onClose: () => void
}

/**
 * Mobile navigation dialog. Focus trap, Escape and return-focus live here
 * so the shared Modal (TC-14-003) stays untouched.
 */
export function NavDrawer({ open, onClose }: NavDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    if (window.matchMedia(APP_NAV_DOCK_MEDIA).matches) return
    const panel = panelRef.current
    if (!panel) return

    const closeButton = panel.querySelector<HTMLElement>('[data-nav-drawer-close]')
    closeButton?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusableIn(panel)
      if (items.length === 0) {
        event.preventDefault()
        panel.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div
        className="absolute inset-0"
        style={{ background: 'var(--tc-overlay)' }}
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        id="app-navigation"
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-navigation-title"
        tabIndex={-1}
        className="absolute inset-y-0 left-0 flex w-[min(18rem,calc(100%-2.5rem))] max-w-full flex-col border-r border-tc-border shadow-[var(--tc-shadow)] outline-none"
        style={{ background: 'var(--tc-sidebar)' }}
      >
        <div className="flex shrink-0 items-center justify-between gap-tc-3 border-b border-tc-border px-tc-4 py-tc-3">
          <h2 id="app-navigation-title" className="text-tc-label font-semibold text-tc-text">
            Navigation
          </h2>
          <button
            type="button"
            data-nav-drawer-close
            onClick={onClose}
            className="inline-flex min-h-tc-8 items-center justify-center rounded-tc-xs border border-tc-border-strong px-tc-3 text-tc-label font-medium text-tc-text hover:bg-[var(--tc-hover)]"
          >
            Close
          </button>
        </div>
        <Sidebar onNavigate={onClose} className="min-h-0 flex-1 border-r-0" />
      </div>
    </div>
  )
}
