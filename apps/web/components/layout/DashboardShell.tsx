'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { APP_NAV_COMPACT_MEDIA } from '@/lib/app-navigation'
import { MfaRequiredBanner } from './MfaRequiredBanner'
import { NavDrawer } from './NavDrawer'
import { SecurityAlertsBanner } from './SecurityAlertsBanner'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { Spinner } from '@/components/ui/Spinner'
import { RouteProgress } from '@/components/ui/RouteProgress'

interface DashboardShellProps {
  children: React.ReactNode
}

export function DashboardShell({ children }: DashboardShellProps) {
  const { user, loading, needs_onboarding, error, refresh } = useAuth()
  const pathname = usePathname()
  const [navOpen, setNavOpen] = useState(false)
  const [compact, setCompact] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const backgroundRef = useRef<HTMLDivElement>(null)
  const navWasOpen = useRef(false)

  useEffect(() => {
    const media = window.matchMedia(APP_NAV_COMPACT_MEDIA)
    const apply = () => {
      const isCompact = media.matches
      setCompact(isCompact)
      if (!isCompact) setNavOpen(false)
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    setNavOpen(false)
  }, [pathname])

  useEffect(() => {
    const background = backgroundRef.current
    if (!background) return
    if (compact && navOpen) background.setAttribute('inert', '')
    else background.removeAttribute('inert')
  }, [compact, navOpen])

  useEffect(() => {
    if (navWasOpen.current && !navOpen) {
      const button = menuButtonRef.current
      if (button && button.offsetParent !== null) button.focus()
    }
    navWasOpen.current = navOpen
  }, [navOpen])

  useEffect(() => {
    if (loading) return
    if (!user && !error) {
      const next = pathname
        ? `/login?next=${encodeURIComponent(pathname)}`
        : '/login'
      window.location.href = next
      return
    }
    if (needs_onboarding) {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentional full page load to reset client auth/workspace state (pre-existing; TC-02-006)
      window.location.href = '/onboarding'
    }
  }, [user, loading, needs_onboarding, error, pathname])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3">
        <Spinner size="lg" />
        <p className="text-[var(--tc-muted)] text-sm">Loading workspace…</p>
      </div>
    )
  }

  if (!user && error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-4">
        <p className="text-tc-label text-tc-danger">{error}</p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => refresh()}
            className="tc-btn-primary min-h-tc-6 rounded-tc-sm px-tc-4 py-tc-2 text-tc-label font-medium"
          >
            Retry
          </button>
          <button
            type="button"
            onClick={() => {
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentional full page load to reset client auth/workspace state (pre-existing; TC-02-006)
              window.location.href = '/login'
            }}
            className="min-h-tc-6 rounded-tc-sm border border-tc-border-strong px-tc-4 py-tc-2 text-tc-label font-medium text-tc-text hover:bg-[var(--tc-hover)]"
          >
            Back to login
          </button>
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3">
        <Spinner size="lg" />
        <p className="text-[var(--tc-muted)] text-sm">Redirecting…</p>
      </div>
    )
  }

  return (
    <>
      <RouteProgress />
      <div className="relative z-[1] flex h-dvh max-h-dvh w-full min-w-0 max-w-full flex-col overflow-hidden bg-tc-bg">
        <nav aria-label="Skip">
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:left-tc-4 focus:top-tc-4 focus:z-[80] focus:rounded-tc-xs focus:border focus:border-tc-border-strong focus:bg-tc-surface-overlay focus:px-tc-4 focus:py-tc-2 focus:text-tc-label focus:font-medium focus:text-tc-text"
          >
            Skip to main content
          </a>
        </nav>
        <div
          ref={backgroundRef}
          className="flex min-h-0 min-w-0 flex-1 flex-col"
        >
          <Topbar
            navOpen={navOpen}
            onToggleNav={() => setNavOpen((open) => !open)}
            menuButtonRef={menuButtonRef}
          />
          <div className="shrink-0">
            <MfaRequiredBanner />
            <SecurityAlertsBanner />
          </div>
          <div className="grid min-h-0 min-w-0 flex-1 grid-cols-1 md:grid-cols-[minmax(200px,240px)_minmax(0,1fr)] lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]">
            {!(compact && navOpen) && (
              <Sidebar className="hidden h-full md:flex" />
            )}
            <main
              id="main-content"
              tabIndex={-1}
              className="relative z-0 min-h-0 min-w-0 overflow-x-hidden overflow-y-auto px-3 pb-6 pt-4 outline-none sm:px-4 sm:pt-5 md:px-5"
            >
              {children}
            </main>
          </div>
        </div>
        {compact && (
          <NavDrawer open={navOpen} onClose={() => setNavOpen(false)} />
        )}
      </div>
    </>
  )
}
