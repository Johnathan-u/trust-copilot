'use client'

import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Input,
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

const ALREADY_CREATED =
  'This link was already created. Rotate it to get a new link.'

function createOutcome(
  body: unknown
): { kind: 'link'; token: string } | { kind: 'again' } | { kind: 'missing' } {
  if (!body || typeof body !== 'object') return { kind: 'missing' }
  const row = body as Record<string, unknown>
  if (row.token_available === false) return { kind: 'again' }
  const token = row.access_token
  if (typeof token === 'string' && token.trim()) return { kind: 'link', token }
  return { kind: 'missing' }
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
  const [spaceName, setSpaceName] = useState('')
  const [createKey, setCreateKey] = useState<string | null>(null)
  const [createdAgain, setCreatedAgain] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
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

  const onNameChange = (value: string) => {
    setSpaceName(value)
    setCreateKey(null)
    setCreatedAgain(false)
    setCreateError(null)
  }

  const createSpace = async () => {
    const name = spaceName.trim()
    if (!name) return
    const key = createKey ?? crypto.randomUUID()
    if (createKey == null) setCreateKey(key)
    setCreateError(null)
    const response = await fetch('/api/shareable-spaces', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': key,
      },
      body: JSON.stringify({ name }),
    })
    if (!response.ok) {
      setCreatedAgain(false)
      setCreateError('The space could not be created.')
      return
    }
    const outcome = createOutcome(await response.json())
    if (outcome.kind === 'again') {
      setRevealed(null)
      setCreatedAgain(true)
      setLoadAttempt((attempt) => attempt + 1)
      return
    }
    if (outcome.kind === 'link') {
      setCreatedAgain(false)
      setCopied(false)
      setCopyError(null)
      setRevealed(buyerAccessLink(window.location.origin, outcome.token))
      setLoadAttempt((attempt) => attempt + 1)
      return
    }
    setCreatedAgain(false)
    setCreateError('The space could not be created.')
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

      {canAdmin && (
        <form
          className="flex flex-col gap-tc-3"
          onSubmit={(event) => {
            event.preventDefault()
            void createSpace()
          }}
        >
          <Input
            label="Name"
            name="name"
            value={spaceName}
            onChange={(event) => onNameChange(event.target.value)}
          />
          <div>
            <Button type="submit" size="sm">
              Create space
            </Button>
          </div>
          {createdAgain ? (
            <p role="status" className="text-tc-label text-tc-text">
              {ALREADY_CREATED}
            </p>
          ) : null}
          {createError ? (
            <p role="alert" className="text-tc-label text-tc-danger">
              {createError}
            </p>
          ) : null}
        </form>
      )}

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
