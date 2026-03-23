'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center p-8 text-center">
      <h1 className="mb-2 text-xl font-semibold text-[var(--tc-text)]">Something went wrong</h1>
      <p className="mb-6 max-w-md text-sm text-[var(--tc-muted)]">
        An unexpected error occurred. You can try again or return to the dashboard.
      </p>
      <div className="flex gap-3">
        <Button onClick={() => reset()}>Try again</Button>
        <Button variant="ghost" onClick={() => (window.location.href = '/dashboard')}>
          Go to dashboard
        </Button>
      </div>
    </div>
  )
}
