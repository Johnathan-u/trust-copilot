'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Button, Card, Input } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

export default function SettingsPage() {
  const { permissions, refresh, switchWorkspace, workspace, workspaces } = useAuth()
  const [createWorkspaceName, setCreateWorkspaceName] = useState('')
  const [createWorkspaceLoading, setCreateWorkspaceLoading] = useState(false)
  const [createWorkspaceError, setCreateWorkspaceError] = useState('')

  return (
    <div>
      <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-6">Settings</h1>

      <Card className="mb-6">
        <p className="text-[var(--tc-muted)] mb-4">Workspace and user settings.</p>
        {workspaces.length > 1 && (
          <div className="max-w-sm">
            <label htmlFor="settings-workspace-select" className="block text-sm font-medium text-[var(--tc-text)] mb-1">
              Active workspace
            </label>
            <select
              id="settings-workspace-select"
              aria-label="Switch workspace"
              value={workspace?.id ?? ''}
              onChange={async (e) => {
                const id = parseInt(e.target.value, 10)
                if (!Number.isNaN(id) && id !== workspace?.id) await switchWorkspace(id)
              }}
              className="w-full cursor-pointer rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)] focus:border-[var(--tc-soft)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-soft)]"
              style={{ colorScheme: 'dark' }}
            >
              {workspaces.map((ws: { id: number; name: string }) => (
                <option key={ws.id} value={ws.id}>{ws.name}</option>
              ))}
            </select>
          </div>
        )}
      </Card>

      <Card className="mb-6">
        <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-2">Create workspace</h2>
        <p className="text-sm text-[var(--tc-muted)] mb-4">
          Create a new workspace. You will be the admin and can invite others.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault()
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
                setCreateWorkspaceError(Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail || 'Failed to create')
                return
              }
              setCreateWorkspaceName('')
              await refresh()
              if (data?.id) await switchWorkspace(data.id)
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
          />
          {createWorkspaceError && <p className="text-sm text-[var(--tc-danger)]">{createWorkspaceError}</p>}
          <Button type="submit" disabled={createWorkspaceLoading || !createWorkspaceName.trim()}>
            {createWorkspaceLoading ? 'Creating…' : 'Create workspace'}
          </Button>
        </form>
      </Card>

      <Card>
        <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-2">Security</h2>
        <p className="text-sm text-[var(--tc-muted)] mb-3">
          Manage your password, two-factor authentication, sessions, and workspace security policy.
        </p>
        <Link href="/dashboard/security">
          <Button variant="secondary">Go to Account Security</Button>
        </Link>
      </Card>
    </div>
  )
}
