'use client'

import { useState } from 'react'

import {
  WorkspaceCreateNotice,
  useCreationBlock,
} from '@/components/WorkspaceCreateNotice'
import { Button, Input } from '@/components/ui'
import {
  WORKSPACE_THROTTLE_READY_MESSAGE,
  classifyWorkspaceCreateResponse,
  type WorkspaceCreateKind,
} from '@/lib/workspace-create-response'

/**
 * Workspace name form. The button stays on the progress label until the
 * request finishes. A refusal still uses the fixed invitation, maximum,
 * and wait copy.
 */
export function WorkspaceCreateForm({
  onCreated,
}: {
  onCreated: (workspaceId: number | null) => Promise<void> | void
}) {
  const [createWorkspaceName, setCreateWorkspaceName] = useState('')
  const [createWorkspaceLoading, setCreateWorkspaceLoading] = useState(false)
  const [createWorkspaceError, setCreateWorkspaceError] = useState('')
  const [notice, setNotice] = useState<{
    id: number
    kind: Exclude<WorkspaceCreateKind, 'generic'>
    message: string
  } | null>(null)
  const [creationClosed, setCreationClosed] = useState(false)
  const { blocked: retryBlocked, blockFor } = useCreationBlock(() => {
    setNotice((current) => {
      if (!current || current.kind !== 'throttled') return current
      return { ...current, message: WORKSPACE_THROTTLE_READY_MESSAGE }
    })
  })
  const createDisabled = creationClosed || retryBlocked

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault()
        if (createWorkspaceLoading || createDisabled) return
        if (!createWorkspaceName.trim()) return
        setCreateWorkspaceError('')
        setCreateWorkspaceLoading(true)
        try {
          const res = await fetch('/api/workspaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ name: createWorkspaceName.trim() }),
          })
          const data = await res.json().catch(() => ({}))
          if (!res.ok) {
            const result = classifyWorkspaceCreateResponse(
              res.status,
              data,
              res.headers.get('Retry-After'),
              'Failed to create'
            )
            if (result.kind === 'generic') {
              setNotice(null)
              blockFor(null)
              setCreateWorkspaceError(
                Array.isArray(data.detail)
                  ? data.detail[0]?.msg
                  : data.detail || 'Failed to create'
              )
              return
            }
            setCreateWorkspaceError('')
            const denial = result
            setNotice((current) => ({
              id: (current?.id ?? 0) + 1,
              kind: denial.kind,
              message: denial.message,
            }))
            if (denial.kind === 'invitation') setCreationClosed(true)
            blockFor(
              denial.kind === 'throttled' ? denial.retryAfterSeconds : null
            )
            return
          }
          setNotice(null)
          setCreateWorkspaceName('')
          const workspaceId = typeof data?.id === 'number' ? data.id : null
          await onCreated(workspaceId)
        } finally {
          setCreateWorkspaceLoading(false)
        }
      }}
      className="space-y-3 max-w-sm"
    >
      <Input
        label="Workspace name"
        type="text"
        placeholder="My workspace"
        value={createWorkspaceName}
        onChange={(e) => setCreateWorkspaceName(e.target.value)}
        maxLength={255}
        disabled={creationClosed}
      />
      {notice ? (
        <WorkspaceCreateNotice
          key={notice.id}
          kind={notice.kind}
          message={notice.message}
        />
      ) : createWorkspaceError ? (
        <p className="text-sm text-[var(--tc-danger)]">
          {createWorkspaceError}
        </p>
      ) : null}
      <Button
        type="submit"
        data-testid="workspace-create-submit"
        disabled={
          createWorkspaceLoading ||
          createDisabled ||
          !createWorkspaceName.trim()
        }
        aria-describedby={notice ? 'workspace-create-notice' : undefined}
      >
        {createWorkspaceLoading ? 'Creating…' : 'Create workspace'}
      </Button>
    </form>
  )
}
