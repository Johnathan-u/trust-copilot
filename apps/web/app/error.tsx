'use client'

import { useEffect } from 'react'
import { Button, ErrorState } from '@/components/ui'
import { presentHttpFailure } from '@/lib/api-error'

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
    <div className="flex min-h-[50vh] items-center justify-center p-8">
      <ErrorState
        failure={presentHttpFailure({ status: 500 })}
        onRetry={() => reset()}
        headingLevel="h1"
        secondary={
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentional full page load to reset client auth/workspace state (pre-existing; TC-02-006)
              window.location.href = '/dashboard'
            }}
          >
            Go to dashboard
          </Button>
        }
      />
    </div>
  )
}
