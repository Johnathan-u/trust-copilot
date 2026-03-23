'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Card } from '@/components/ui'

/**
 * In local/dev, NEXT_PUBLIC_TRUST_DEFAULT_SLUG can be set to auto-redirect
 * /trust to /trust/{slug}. In production this should NOT be set — users
 * must use the workspace-specific link they were given.
 */
const DEFAULT_SLUG = process.env.NEXT_PUBLIC_TRUST_DEFAULT_SLUG || ''

export default function TrustLandingPage() {
  const router = useRouter()
  const [redirecting, setRedirecting] = useState(false)

  useEffect(() => {
    if (DEFAULT_SLUG) {
      setRedirecting(true)
      router.replace(`/trust/${DEFAULT_SLUG}`)
    }
  }, [router])

  if (redirecting) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />
      </div>
    )
  }

  return (
    <div className="relative min-h-screen">
      <header className="sticky top-0 z-10 border-b border-[var(--tc-border)] bg-[var(--tc-panel)]/95 backdrop-blur-md py-4 px-6">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-bold tracking-tight text-[var(--tc-text)]">Trust Center</h1>
          <Link href="/login" className="text-sm font-medium text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition-colors">Sign in</Link>
        </div>
      </header>
      <main className="flex flex-col items-center justify-center px-6 py-24">
        <Card className="max-w-lg w-full text-center" padding="lg">
          <div className="flex justify-center mb-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--tc-primary)]/15 text-[var(--tc-primary)] text-xl">
              🔒
            </div>
          </div>
          <h2 className="text-lg font-bold text-[var(--tc-text)] mb-2">Trust Center</h2>
          <p className="text-sm text-[var(--tc-muted)] mb-6">
            To view security and compliance information or submit a trust request, please use the
            workspace-specific trust link you were given.
          </p>
          <p className="text-xs text-[var(--tc-muted)]">
            Trust links look like: <span className="font-mono text-[var(--tc-text)]">/trust/your-company</span>
          </p>
        </Card>
        <Link href="/login" className="mt-6 text-sm text-[var(--tc-primary)] hover:underline">
          Or sign in to your workspace
        </Link>
      </main>
    </div>
  )
}
