'use client'

import { useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { MfaRequiredBanner } from './MfaRequiredBanner'
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

  useEffect(() => {
    if (loading) return
    if (!user && !error) {
      const next = pathname ? `/login?next=${encodeURIComponent(pathname)}` : '/login'
      window.location.href = next
      return
    }
    if (needs_onboarding) {
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
            onClick={() => { window.location.href = '/login' }}
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
      <div
        className="relative z-[1] grid min-h-screen w-full max-w-full min-w-0 grid-cols-[minmax(160px,200px)_minmax(0,1fr)] sm:grid-cols-[minmax(180px,220px)_minmax(0,1fr)] md:grid-cols-[minmax(200px,240px)_minmax(0,1fr)] lg:grid-cols-[minmax(220px,260px)_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]"
        style={{
          gridTemplateRows: 'auto auto minmax(0, 1fr)',
        }}
      >
        <div className="col-span-2 min-w-0">
          <Topbar />
        </div>
        <div className="col-span-2 min-w-0 space-y-0">
          <MfaRequiredBanner />
          <SecurityAlertsBanner />
        </div>
        <Sidebar />
        <main className="relative z-0 min-h-0 min-w-0 overflow-x-auto overflow-y-auto px-3 pb-6 pt-4 sm:px-4 sm:pt-5 md:px-5">
          {children}
        </main>
      </div>
    </>
  )
}
