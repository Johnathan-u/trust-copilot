'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { APP_NAV_COMPACT_MEDIA } from '@/lib/app-navigation'
import { navOpenForPath } from '@/lib/render-state'
import { Button, ErrorState, LoadingState } from '@/components/ui'
import { MfaRequiredBanner } from './MfaRequiredBanner'
import { NavDrawer } from './NavDrawer'
import { SecurityAlertsBanner } from './SecurityAlertsBanner'
import { ShellAlertsProvider } from './ShellAlerts'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { RouteProgress } from '@/components/ui/RouteProgress'

interface DashboardShellProps {
  children: React.ReactNode
}

export function DashboardShell({ children }: DashboardShellProps) {
  const {
    user,
    loading,
    needs_onboarding,
    error,
    failure,
    requestId,
    refresh,
  } = useAuth()
  const pathname = usePathname()
  const [navOpen, setNavOpen] = useState(false)
  const [compact, setCompact] = useState(false)
  const [seenPath, setSeenPath] = useState(pathname)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  if (seenPath !== pathname) {
    const nextOpen = navOpenForPath(seenPath, pathname, navOpen)
    setSeenPath(pathname)
    if (nextOpen !== navOpen) setNavOpen(nextOpen)
  }

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
      <div className="flex min-h-screen items-center justify-center p-tc-6">
        <LoadingState
          label="Loading workspace"
          onRetry={() => void refresh()}
          resetKey={requestId}
        >
          <div className="flex flex-col items-center gap-tc-3">
            <div
              aria-hidden
              className="tc-skeleton h-8 w-8 animate-spin rounded-full border-2 border-tc-muted border-t-tc-primary motion-reduce:animate-none"
            />
            <p className="text-tc-label text-tc-muted">Loading workspace…</p>
          </div>
        </LoadingState>
      </div>
    )
  }

  if (!user && (failure || error)) {
    return (
      <div className="flex min-h-screen items-center justify-center p-tc-4">
        <div className="w-full max-w-md">
          <ErrorState
            failure={
              failure ?? {
                kind: 'rejected',
                title: 'Could not load this',
                description: 'The request did not succeed. Try again.',
              }
            }
            headingLevel="h1"
            onRetry={() => void refresh()}
            secondary={
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentional full page load to reset client auth/workspace state (pre-existing; TC-02-006)
                  window.location.href = '/login'
                }}
              >
                Back to login
              </Button>
            }
          />
        </div>
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center p-tc-6">
        <p className="text-tc-label text-tc-muted">Redirecting…</p>
      </div>
    )
  }

  return (
    <>
      <RouteProgress />
      <ShellAlertsProvider>
        <div className="relative z-[1] flex h-dvh max-h-dvh w-full min-w-0 max-w-full flex-col overflow-hidden bg-tc-bg">
          <nav aria-label="Skip">
            <a
              href="#main-content"
              className="sr-only focus:not-sr-only focus:absolute focus:left-tc-4 focus:top-tc-4 focus:z-[80] focus:rounded-tc-xs focus:border focus:border-tc-border-strong focus:bg-tc-surface-overlay focus:px-tc-4 focus:py-tc-2 focus:text-tc-label focus:font-medium focus:text-tc-text"
            >
              Skip to main content
            </a>
          </nav>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
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
            <NavDrawer
              open={navOpen}
              onClose={() => setNavOpen(false)}
              returnFocusRef={menuButtonRef}
            />
          )}
        </div>
      </ShellAlertsProvider>
    </>
  )
}
