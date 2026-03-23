'use client'

import { useEffect, useState, useCallback } from 'react'
import { Button, Card, Input, Modal, Toast, TableSkeleton } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { formatApiErrorDetail } from '@/lib/api-error'

type Member = {
  id: number
  user_id: number
  email: string
  display_name: string
  role: string
  suspended: boolean
  created_at: string | null
}

type Invite = {
  id: number
  email: string
  role: string
  expires_at: string | null
  created_at: string | null
  invited_by: string | null
}

type RoleDef = {
  id: number | null
  name: string
  description?: string
  builtin: boolean
  can_edit: boolean
  can_review: boolean
  can_export: boolean
  can_admin: boolean
}

type ConfirmAction = {
  title: string
  body: string
  confirmLabel: string
  variant: 'danger' | 'warning' | 'default'
  onConfirm: () => Promise<void>
}

type ToastState = {
  title: string
  message: string
  type: 'success' | 'error' | 'info'
} | null

const BUILTIN_ROLES = ['admin', 'editor', 'reviewer']

export default function MembersPage() {
  const { user, permissions, workspace } = useAuth()
  const canAdmin = permissions.can_admin
  const [members, setMembers] = useState<Member[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [roles, setRoles] = useState<RoleDef[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<string>('editor')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [roleModalOpen, setRoleModalOpen] = useState(false)
  const [newRoleName, setNewRoleName] = useState('')
  const [newRolePerms, setNewRolePerms] = useState({ can_edit: false, can_review: true, can_export: false, can_admin: false })
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [toast, setToast] = useState<ToastState>(null)

  const showToast = useCallback((title: string, message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ title, message, type })
    setTimeout(() => setToast(null), 4000)
  }, [])

  const load = () => {
    if (members.length === 0) setLoading(true)
    setRefreshing(true)
    Promise.all([
      fetch('/api/members', { credentials: 'include' }),
      fetch('/api/members/invites', { credentials: 'include' }),
      fetch('/api/members/roles', { credentials: 'include' }),
    ])
      .then(([r1, r2, r3]) => Promise.all([
        r1.ok ? r1.json() : { members: [] },
        r2.ok ? r2.json() : { invites: [] },
        r3.ok ? r3.json() : { roles: [] },
      ]))
      .then(([d1, d2, d3]) => {
        setMembers(d1.members ?? [])
        setInvites(d2.invites ?? [])
        setRoles(d3.roles ?? [])
      })
      .catch(() => { setMembers([]); setInvites([]); setRoles([]) })
      .finally(() => { setLoading(false); setRefreshing(false) })
  }

  const allRoleNames = roles.length > 0 ? roles.map(r => r.name) : BUILTIN_ROLES

  useEffect(() => {
    if (canAdmin) load()
    else setLoading(false)
  }, [canAdmin, workspace?.id])

  const openConfirm = (action: ConfirmAction) => {
    setConfirmError(null)
    setConfirmBusy(false)
    setConfirmAction(action)
  }

  const runConfirm = async () => {
    if (!confirmAction) return
    setConfirmBusy(true)
    setConfirmError(null)
    try {
      await confirmAction.onConfirm()
      setConfirmAction(null)
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setConfirmBusy(false)
    }
  }

  const createInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    const email = inviteEmail.trim().toLowerCase()
    if (!email || !email.includes('@')) {
      setError('Enter a valid email')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch('/api/members/invites', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, role: inviteRole }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(formatApiErrorDetail(data, 'Failed to invite'))
        return
      }
      setInviteOpen(false)
      setInviteEmail('')
      setInviteRole('editor')
      showToast('Invite sent', `Invitation sent to ${email}.`)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const revokeInvite = (id: number, email: string) => {
    openConfirm({
      title: 'Revoke invitation',
      body: `Revoke the pending invitation for ${email}? They will no longer be able to accept it.`,
      confirmLabel: 'Revoke',
      variant: 'danger',
      onConfirm: async () => {
        const res = await fetch(`/api/members/invites/${id}`, { method: 'DELETE', credentials: 'include' })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.detail || 'Failed to revoke invite')
        }
        showToast('Invite revoked', `Invitation for ${email} has been revoked.`)
        load()
      },
    })
  }

  const updateRole = async (memberId: number, role: string) => {
    const res = await fetch(`/api/members/${memberId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
    if (res.ok) {
      showToast('Role updated', `Member role changed to ${role}.`)
      load()
    } else {
      const data = await res.json().catch(() => ({}))
      showToast('Error', data.detail || 'Failed to update role', 'error')
    }
  }

  const removeMember = (member: Member) => {
    openConfirm({
      title: 'Remove member',
      body: `Remove ${member.display_name || member.email} from this workspace? They will lose access immediately.`,
      confirmLabel: 'Remove',
      variant: 'danger',
      onConfirm: async () => {
        const res = await fetch(`/api/members/${member.id}`, { method: 'DELETE', credentials: 'include' })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.detail || 'Failed to remove member')
        }
        showToast('Member removed', `${member.display_name || member.email} has been removed.`)
        load()
      },
    })
  }

  const toggleSuspend = (member: Member, suspend: boolean) => {
    const action = suspend ? 'Suspend' : 'Activate'
    openConfirm({
      title: `${action} member`,
      body: suspend
        ? `Suspend ${member.display_name || member.email}? They will not be able to access this workspace.`
        : `Reactivate ${member.display_name || member.email}? They will regain access to this workspace.`,
      confirmLabel: action,
      variant: suspend ? 'warning' : 'default',
      onConfirm: async () => {
        const res = await fetch(`/api/members/${member.id}/suspend`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ suspended: suspend }),
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.detail || `Failed to ${action.toLowerCase()} member`)
        }
        showToast(`Member ${action.toLowerCase()}ed`, `${member.display_name || member.email} has been ${action.toLowerCase()}ed.`)
        load()
      },
    })
  }

  const revokeSessions = (member: Member) => {
    openConfirm({
      title: 'Revoke sessions',
      body: `Sign out ${member.display_name || member.email} from all devices? They will need to log in again.`,
      confirmLabel: 'Revoke sessions',
      variant: 'warning',
      onConfirm: async () => {
        const res = await fetch(`/api/members/${member.id}/revoke-sessions`, {
          method: 'POST',
          credentials: 'include',
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || 'Failed to revoke sessions')
        showToast('Sessions revoked', `Revoked ${data.revoked ?? 0} session(s) for ${member.display_name || member.email}.`)
      },
    })
  }

  const deleteRole = (role: RoleDef) => {
    openConfirm({
      title: 'Delete role',
      body: `Delete the "${role.name}" role? Members using it will be reverted to reviewer.`,
      confirmLabel: 'Delete role',
      variant: 'danger',
      onConfirm: async () => {
        const res = await fetch(`/api/members/roles/${role.id}`, { method: 'DELETE', credentials: 'include' })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.detail || 'Failed to delete role')
        }
        showToast('Role deleted', `Role "${role.name}" has been deleted.`)
        load()
      },
    })
  }

  if (!canAdmin) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-6">Members</h1>
        <Card>
          <p className="text-[var(--tc-muted)]">You need admin access to manage members.</p>
        </Card>
      </div>
    )
  }

  if (loading) {
    return (
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)] mb-6">Members</h1>
        <Card><TableSkeleton rows={4} cols={5} /></Card>
      </div>
    )
  }

  const confirmBtnClass =
    confirmAction?.variant === 'danger'
      ? 'bg-red-600 hover:bg-red-700 text-white'
      : confirmAction?.variant === 'warning'
        ? 'bg-amber-600 hover:bg-amber-700 text-white'
        : ''

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Members</h1>
        {refreshing && !loading && <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />}
      </div>

      <Card className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-[var(--tc-text)]">Workspace members</h2>
          <Button onClick={() => { setInviteOpen(true); setError(null) }}>Invite</Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--tc-border)] text-left text-[var(--tc-muted)]">
                <th className="pb-2 pr-4">Email</th>
                <th className="pb-2 pr-4">Role</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2 pr-4">Joined</th>
                <th className="pb-2 w-48" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className={`border-b border-white/5 ${m.suspended ? 'opacity-50' : ''}`}>
                  <td className="py-3 pr-4 text-[var(--tc-text)]">
                    {m.display_name || m.email}
                    {user?.id === m.user_id && <span className="ml-2 text-xs text-[var(--tc-muted)]">(you)</span>}
                  </td>
                  <td className="py-3 pr-4">
                    <select
                      className="rounded border border-[var(--tc-border)] px-2 py-1 text-[var(--tc-text)]"
                      value={m.role}
                      onChange={(e) => updateRole(m.id, e.target.value)}
                      disabled={m.suspended || (user?.id === m.user_id && members.filter((x) => x.role === 'admin').length <= 1)}
                    >
                      {allRoleNames.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td className="py-3 pr-4">
                    {m.suspended
                      ? <span className="inline-block rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">Suspended</span>
                      : <span className="inline-block rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">Active</span>}
                  </td>
                  <td className="py-3 pr-4 text-[var(--tc-muted)]">
                    {m.created_at ? new Date(m.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="py-3 flex gap-1 flex-wrap">
                    {user?.id !== m.user_id && (
                      <>
                        <Button
                          variant="ghost"
                          className={`text-xs ${m.suspended ? 'text-emerald-400' : 'text-amber-400'}`}
                          onClick={() => toggleSuspend(m, !m.suspended)}
                        >
                          {m.suspended ? 'Activate' : 'Suspend'}
                        </Button>
                        <Button
                          variant="ghost"
                          className="text-xs text-[var(--tc-muted)]"
                          onClick={() => revokeSessions(m)}
                        >
                          Revoke sessions
                        </Button>
                      </>
                    )}
                    <Button
                      variant="ghost"
                      className="text-xs text-[var(--tc-danger)]"
                      disabled={user?.id === m.user_id && members.filter((x) => x.role === 'admin').length <= 1}
                      onClick={() => removeMember(m)}
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mb-6">
        <h2 className="text-lg font-semibold text-[var(--tc-text)] mb-4">Pending invites</h2>
        {invites.length === 0 ? (
          <p className="text-sm text-[var(--tc-muted)]">No pending invites.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--tc-border)] text-left text-[var(--tc-muted)]">
                  <th className="pb-2 pr-4">Email</th>
                  <th className="pb-2 pr-4">Role</th>
                  <th className="pb-2 pr-4">Sent</th>
                  <th className="pb-2 pr-4">Expires</th>
                  <th className="pb-2 pr-4">Invited by</th>
                  <th className="pb-2 w-24" />
                </tr>
              </thead>
              <tbody>
                {invites.map((inv) => {
                  const expired = inv.expires_at ? new Date(inv.expires_at) < new Date() : false
                  return (
                    <tr key={inv.id} className={`border-b border-white/5 ${expired ? 'opacity-50' : ''}`}>
                      <td className="py-3 pr-4 text-[var(--tc-text)]">
                        {inv.email}
                        {expired && <span className="ml-2 text-xs text-[var(--tc-danger)]">expired</span>}
                      </td>
                      <td className="py-3 pr-4 text-[var(--tc-muted)]">{inv.role}</td>
                      <td className="py-3 pr-4 text-[var(--tc-muted)]">
                        {inv.created_at ? new Date(inv.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-3 pr-4 text-[var(--tc-muted)]">
                        {inv.expires_at ? new Date(inv.expires_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="py-3 pr-4 text-[var(--tc-muted)]">
                        {inv.invited_by || '—'}
                      </td>
                      <td className="py-3">
                        <Button variant="ghost" className="text-xs text-[var(--tc-danger)]" onClick={() => revokeInvite(inv.id, inv.email)}>
                          Revoke
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="mt-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-[var(--tc-text)]">Roles</h2>
          <Button onClick={() => { setRoleModalOpen(true); setError(null) }}>Create role</Button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--tc-border)] text-left text-[var(--tc-muted)]">
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">Edit</th>
                <th className="pb-2 pr-4">Review</th>
                <th className="pb-2 pr-4">Export</th>
                <th className="pb-2 pr-4">Admin</th>
                <th className="pb-2 w-24" />
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.name} className="border-b border-white/5">
                  <td className="py-3 pr-4 text-[var(--tc-text)]">
                    {r.name}
                    {r.builtin && <span className="ml-2 text-xs text-[var(--tc-muted)]">(built-in)</span>}
                  </td>
                  <td className="py-3 pr-4">{r.can_edit ? '✓' : '—'}</td>
                  <td className="py-3 pr-4">{r.can_review ? '✓' : '—'}</td>
                  <td className="py-3 pr-4">{r.can_export ? '✓' : '—'}</td>
                  <td className="py-3 pr-4">{r.can_admin ? '✓' : '—'}</td>
                  <td className="py-3">
                    {!r.builtin && r.id && (
                      <Button variant="ghost" className="text-xs text-[var(--tc-danger)]" onClick={() => deleteRole(r)}>
                        Delete
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Confirmation modal — replaces all native alert/confirm */}
      <Modal isOpen={!!confirmAction} onClose={() => { if (!confirmBusy) setConfirmAction(null) }} title={confirmAction?.title}>
        <div className="space-y-4">
          <p className="text-sm text-[var(--tc-muted)]">{confirmAction?.body}</p>
          {confirmError && <p className="text-sm text-[var(--tc-danger)]">{confirmError}</p>}
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" onClick={() => setConfirmAction(null)} disabled={confirmBusy}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={runConfirm}
              disabled={confirmBusy}
              className={confirmBtnClass}
            >
              {confirmBusy ? 'Working…' : confirmAction?.confirmLabel}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Create role modal */}
      <Modal isOpen={roleModalOpen} onClose={() => setRoleModalOpen(false)} title="Create custom role">
        <form onSubmit={async (e) => {
          e.preventDefault()
          const name = newRoleName.trim().toLowerCase()
          if (!name) { setError('Enter a role name'); return }
          setSubmitting(true); setError(null)
          try {
            const res = await fetch('/api/members/roles', {
              method: 'POST', credentials: 'include',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name, ...newRolePerms }),
            })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) { setError(data.detail || 'Failed'); return }
            setRoleModalOpen(false); setNewRoleName(''); setNewRolePerms({ can_edit: false, can_review: true, can_export: false, can_admin: false })
            showToast('Role created', `Custom role "${name}" has been created.`)
            load()
          } finally { setSubmitting(false) }
        }} className="space-y-4">
          <Input label="Role name" value={newRoleName} onChange={(e) => setNewRoleName(e.target.value)} placeholder="e.g. auditor" required />
          <div className="space-y-2">
            <label className="block text-sm font-medium text-[var(--tc-text)]">Permissions</label>
            {(['can_review', 'can_edit', 'can_export', 'can_admin'] as const).map((perm) => (
              <label key={perm} className="flex items-center gap-2 text-sm text-[var(--tc-text)]">
                <input type="checkbox" checked={newRolePerms[perm]} onChange={(e) => setNewRolePerms({ ...newRolePerms, [perm]: e.target.checked })} className="h-4 w-4" />
                {perm.replace('can_', '')}
              </label>
            ))}
          </div>
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" onClick={() => setRoleModalOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Creating…' : 'Create role'}</Button>
          </div>
        </form>
      </Modal>

      {/* Invite modal */}
      <Modal isOpen={inviteOpen} onClose={() => { if (!submitting) setInviteOpen(false) }} title="Invite to workspace">
        <form onSubmit={createInvite} className="space-y-4">
          <Input
            label="Email"
            type="email"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            placeholder="colleague@example.com"
            required
            disabled={submitting}
          />
          <div>
            <label className="block text-sm font-medium text-[var(--tc-text)] mb-1">Role</label>
            <select
              className="w-full rounded border border-[var(--tc-border)] px-3 py-2 text-[var(--tc-text)]"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              disabled={submitting}
            >
              {allRoleNames.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end">
            <Button type="button" variant="ghost" onClick={() => setInviteOpen(false)} disabled={submitting}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Sending…' : 'Send invite'}</Button>
          </div>
        </form>
      </Modal>

      {/* Toast notification */}
      {toast && <Toast title={toast.title} message={toast.message} type={toast.type} onDismiss={() => setToast(null)} />}
    </div>
  )
}
