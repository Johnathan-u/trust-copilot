'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { WorkspaceCreateForm } from '@/components/WorkspaceCreateForm'
import { signOutToLogin } from '@/components/WorkspaceCreateNotice'
import {
  WorkspaceCreationLoading,
  WorkspaceCreationUnavailable,
} from '@/components/WorkspaceCreationStatus'
import { WorkspaceInvitation } from '@/components/WorkspaceInvitation'
import { useWorkspaceCreationPolicy } from '@/components/useWorkspaceCreationPolicy'
import { Button, Card } from '@/components/ui'

/**
 * Full-page creation entry.
 * `showFormWhenAllowed` restores a name form only when the policy allows it.
 * Checkout leaves this off: that screen stays an invitation either way.
 */
export function WorkspaceCreationEntry({
  heading,
  backHref,
  contactHref = null,
  showFormWhenAllowed = false,
}: {
  heading: string
  backHref: string
  contactHref?: string | null
  showFormWhenAllowed?: boolean
}) {
  const policy = useWorkspaceCreationPolicy()
  const router = useRouter()

  if (policy.phase === 'loading') {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-tc-title font-bold text-tc-text">{heading}</h1>
          <div className="mt-tc-4">
            <WorkspaceCreationLoading className="text-tc-label text-tc-text" />
          </div>
        </Card>
      </main>
    )
  }

  if (policy.phase === 'unavailable') {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-tc-title font-bold text-tc-text">{heading}</h1>
          <div className="mt-tc-4">
            <WorkspaceCreationUnavailable onRetry={policy.retry} />
          </div>
          <div className="mt-tc-4 flex flex-col gap-tc-3">
            <Button
              type="button"
              variant="secondary"
              className="w-full"
              onClick={() => void signOutToLogin()}
            >
              Sign out
            </Button>
            <Link
              href={backHref}
              className="inline-flex min-h-tc-8 items-center justify-center text-tc-label font-semibold text-tc-text underline"
            >
              Back
            </Link>
          </div>
        </Card>
      </main>
    )
  }

  if (policy.phase === 'allowed' && showFormWhenAllowed) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <div data-testid="workspace-creation-form">
            <h1 className="text-tc-title font-bold text-tc-text">{heading}</h1>
            <p className="mb-tc-6 mt-tc-2 text-tc-label text-tc-muted">
              Name your workspace. This is where your team&apos;s documents,
              questionnaires, and compliance data will live.
            </p>
            <WorkspaceCreateForm
              onCreated={async () => {
                router.push('/dashboard')
              }}
            />
            <div className="mt-tc-4 flex flex-col gap-tc-3">
              <Button
                type="button"
                variant="secondary"
                className="w-full"
                onClick={() => void signOutToLogin()}
              >
                Sign out
              </Button>
              <Link
                href={backHref}
                className="inline-flex min-h-tc-8 items-center justify-center text-tc-label font-semibold text-tc-text underline"
              >
                Back
              </Link>
            </div>
          </div>
        </Card>
      </main>
    )
  }

  return (
    <WorkspaceInvitation
      heading={heading}
      backHref={backHref}
      contactHref={contactHref}
    />
  )
}
