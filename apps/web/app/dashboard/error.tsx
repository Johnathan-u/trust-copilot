'use client'

import { useEffect } from 'react'
import { ErrorState } from '@/components/ui'
import { presentHttpFailure } from '@/lib/api-error'

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
    <div className="flex min-h-[40vh] items-center justify-center p-8">
      <ErrorState
        failure={presentHttpFailure({ status: 500 })}
        onRetry={() => reset()}
      />
    </div>
  )
}
