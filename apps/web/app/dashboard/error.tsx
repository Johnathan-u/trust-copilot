'use client'

import { useEffect } from 'react'
import { Button } from '@/components/ui'

export default function DashboardError({
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
    <div className="flex min-h-[40vh] flex-col items-center justify-center p-8 text-center">
      <h2 className="mb-2 text-lg font-semibold text-[var(--tc-text)]">Something went wrong</h2>
      <p className="mb-6 max-w-md text-sm text-[var(--tc-muted)]">
        An error occurred loading this section. You can try again.
      </p>
      <Button onClick={() => reset()}>Try again</Button>
    </div>
  )
}
