'use client'

import { useEffect, useRef } from 'react'
import Link from 'next/link'
import { Button, Card } from '@/components/ui'
import { signOutToLogin } from '@/components/WorkspaceCreateNotice'
import {
  WORKSPACE_INVITATION_MESSAGE,
  WORKSPACE_SALES_MAILTO,
} from '@/lib/workspace-create-response'

/**
 * Shown instead of a workspace creation form.
 * The client cannot tell whether creation would succeed, so these screens
 * do not ask for a workspace and do not send one.
 */
export function WorkspaceInvitation({
  heading,
  backHref,
}: {
  heading: string
  backHref: string
}) {
  const noticeRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    noticeRef.current?.focus()
  }, [])

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <div data-testid="workspace-invitation">
          <h1 className="text-tc-title font-bold text-tc-text">{heading}</h1>
          <div
            ref={noticeRef}
            tabIndex={-1}
            role="alert"
            data-testid="workspace-invitation-notice"
            className="mt-tc-4 rounded-tc-sm border border-tc-border-strong p-tc-4 text-tc-label text-tc-text focus:outline focus:outline-2 focus:outline-offset-2"
            style={{
              background: 'var(--tc-surface-raised)',
              outlineColor: 'var(--tc-focus)',
            }}
          >
            <p className="font-semibold">Invitation needed</p>
            <p className="mt-tc-1">{WORKSPACE_INVITATION_MESSAGE}</p>
          </div>
          <div className="mt-tc-4 flex flex-col gap-tc-3">
            <a
              href={WORKSPACE_SALES_MAILTO}
              className="inline-flex min-h-tc-8 items-center justify-center rounded-tc-sm border border-tc-border-strong px-tc-4 py-tc-3 text-center text-tc-label font-semibold text-tc-text underline"
              style={{ background: 'var(--tc-surface-raised)' }}
            >
              Contact sales
            </a>
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
