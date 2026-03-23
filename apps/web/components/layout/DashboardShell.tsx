'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
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
  const { user, loading } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (loading) return
    if (!user) {
      const next = pathname ? `/login?next=${encodeURIComponent(pathname)}` : '/login'
      router.replace(next)
    }
  }, [user, loading, router, pathname])

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3">
        <Spinner size="lg" />
        <p className="text-[var(--tc-muted)] text-sm">Loading workspace…</p>
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
