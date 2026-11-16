'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  LoadingState,
  useDestructiveConfirm,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  buyerAccessLink,
  spaceLiveness,
  type SpaceLiveness,
} from '@/lib/shareable-space-link'
import {
  failureOf,
  isAbortError,
  listFromPayload,
  readSectionJson,
} from '@/lib/section-load'
import type { ApiFailurePresentation } from '@/lib/api-error'

type ShareableSpaceRow = {
  id: number
  name: string
  buyer_company: string | null
  is_active: boolean
  expires_at: string | null
  liveness: SpaceLiveness
}

const STATUS_LABEL: Record<SpaceLiveness, string> = {
  live: 'Live',
  inactive: 'Inactive',
  expired: 'Expired',
}

function asSpace(value: unknown, now: number): ShareableSpaceRow | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (typeof row.id !== 'number' || typeof row.name !== 'string') return null
  if (typeof row.is_active !== 'boolean') return null
  const expires = row.expires_at
  const space = {
    id: row.id,
    name: row.name,
    buyer_company:
      typeof row.buyer_company === 'string' ? row.buyer_company : null,
    is_active: row.is_active,
    expires_at: typeof expires === 'string' ? expires : null,
  }
  return { ...space, liveness: spaceLiveness(space, now) }
}

export default function ShareableSpacesPage() {
  const { workspace, permissions } = useAuth()
  const canAdmin = Boolean(permissions?.can_admin)
  const [spaces, setSpaces] = useState<ShareableSpaceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [revealed, setRevealed] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const { confirm, dialog: confirmDialog } = useDestructiveConfirm()

  useEffect(() => {
    let cancelled = false
    fetch('/api/shareable-spaces', { credentials: 'include' })
      .then((response) => readSectionJson(response))
      .then((data) => {
        if (cancelled) return
        const now = Date.now()
        const parsed = listFromPayload<unknown>(data, ['spaces'])
          .map((row) => asSpace(row, now))
          .filter((row): row is ShareableSpaceRow => row != null)
        setSpaces(parsed)
        setLoadFailure(null)
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return
        setSpaces([])
        setLoadFailure(failureOf(error))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [workspace?.id, loadAttempt])

  const dismissLink = () => {
    setRevealed(null)
    setCopied(false)
    setCopyError(null)
  }

  const copyLink = async () => {
    if (!revealed) return
    try {
      await navigator.clipboard.writeText(revealed)
      setCopied(true)
      setCopyError(null)
    } catch {
      setCopied(false)
      setCopyError('The link could not be copied.')
    }
  }

  const askRotate = (space: ShareableSpaceRow) => {
    confirm({
      title: 'Rotate link',
      description: 'The old link will stop working immediately.',
      confirmLabel: 'Rotate link',
      onConfirm: async () => {
        const response = await fetch(
          `/api/shareable-spaces/${space.id}/rotate`,
          { method: 'POST', credentials: 'include' }
        )
        if (!response.ok) {
          throw new Error(
            response.status === 409
              ? 'This space is inactive or expired and was not changed.'
              : 'The link could not be rotated.'
          )
        }
        const body: unknown = await response.json()
        const token =
          body && typeof body === 'object'
            ? (body as { access_token?: unknown }).access_token
            : null
        if (typeof token !== 'string' || !token.trim()) {
          throw new Error('The link could not be rotated.')
        }
        setCopied(false)
        setCopyError(null)
        setRevealed(buyerAccessLink(window.location.origin, token))
        setLoadAttempt((attempt) => attempt + 1)
      },
    })
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-tc-4 px-tc-4 py-tc-6">
      <header className="flex flex-col gap-tc-1">
        <h1 className="text-tc-title font-semibold text-tc-text">
          Shareable spaces
        </h1>
        <p className="text-tc-label text-tc-muted">
          Live spaces are active and not expired. Rotating a link makes the
          previous link stop working immediately. The new link is shown once and
          is not saved.
        </p>
      </header>

      {loading && (
        <LoadingState
          label="Loading shareable spaces"
          onRetry={() => {
            setLoading(true)
            setLoadAttempt((attempt) => attempt + 1)
          }}
        >
          <p className="text-tc-label text-tc-muted">
            Loading shareable spaces…
          </p>
        </LoadingState>
      )}

      {!loading && loadFailure && (
        <ErrorState
          failure={loadFailure}
          onRetry={() => {
            setLoading(true)
            setLoadFailure(null)
            setLoadAttempt((attempt) => attempt + 1)
          }}
        />
      )}

      {!loading && !loadFailure && spaces.length === 0 && (
        <EmptyState
          title="No shareable spaces"
          description="Spaces created for a buyer show up here. A live space can have its link rotated."
        />
      )}

      {!loading && !loadFailure && spaces.length > 0 && (
        <Card padding="sm" className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-tc-label">
            <caption className="sr-only">Shareable spaces</caption>
            <thead>
              <tr className="border-b border-tc-border text-tc-muted">
                <th className="py-tc-2 pr-tc-4 font-medium" scope="col">
                  Name
                </th>
                <th className="py-tc-2 pr-tc-4 font-medium" scope="col">
                  Buyer
                </th>
                <th className="py-tc-2 pr-tc-4 font-medium" scope="col">
                  Status
                </th>
                <th className="py-tc-2 font-medium" scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {spaces.map((space) => {
                const liveness = space.liveness
                return (
                  <tr key={space.id} className="border-b border-tc-border">
                    <td className="py-tc-3 pr-tc-4 font-medium text-tc-text">
                      {space.name}
                    </td>
                    <td className="py-tc-3 pr-tc-4 text-tc-text">
                      {space.buyer_company ?? 'None'}
                    </td>
                    <td className="py-tc-3 pr-tc-4 text-tc-text">
                      {STATUS_LABEL[liveness]}
                    </td>
                    <td className="py-tc-3 text-right">
                      {canAdmin && liveness === 'live' ? (
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          aria-label={`Rotate link for ${space.name}`}
                          onClick={() => askRotate(space)}
                        >
                          Rotate link
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}

      {confirmDialog}

      <Dialog
        open={revealed != null}
        onClose={dismissLink}
        title="New buyer link"
        description="This link is shown once and is not saved. Send it to the buyer. The previous link no longer works."
        size="lg"
      >
        <p className="break-all rounded-tc-sm border border-tc-border bg-tc-surface-sunken p-tc-3 text-tc-label text-tc-text">
          {revealed}
        </p>
        <div className="mt-tc-4 flex items-center justify-end gap-tc-2">
          {copyError ? (
            <p className="mr-auto text-tc-label text-tc-danger" role="alert">
              {copyError}
            </p>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void copyLink()}
          >
            {copied ? 'Copied' : 'Copy link'}
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
