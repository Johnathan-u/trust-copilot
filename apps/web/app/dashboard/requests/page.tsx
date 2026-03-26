'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, Modal, Toast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ──────────────────── Types ──────────────────── */

type VendorRequest = {
  id: number
  vendor_email: string
  questionnaire_id: number | null
  message: string | null
  status: string
  link_token: string | null
  created_at: string | null
}

type Questionnaire = {
  id: number
  filename: string
  status: string
}

/* ──────────────────── Helpers ──────────────────── */

const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  pending:     { label: 'Pending',     color: 'bg-amber-500/15 text-amber-400' },
  in_progress: { label: 'In Progress', color: 'bg-blue-500/15 text-blue-400' },
  completed:   { label: 'Completed',   color: 'bg-emerald-500/15 text-emerald-400' },
}

function statusBadge(status: string) {
  const s = STATUS_STYLE[status] ?? { label: status, color: 'bg-slate-500/15 text-slate-400' }
  return (
    <span className={`text-[11px] font-semibold uppercase px-2 py-0.5 rounded ${s.color}`}>
      {s.label}
    </span>
  )
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

/* ──────────────────── Component ──────────────────── */

export default function RequestsPage() {
  const { workspace, permissions } = useAuth()
  const canEdit = permissions.can_edit
  const canAdmin = permissions.can_admin

  const [requests, setRequests] = useState<VendorRequest[]>([])
  const [questionnaires, setQuestionnaires] = useState<Questionnaire[]>([])
  const [loading, setLoading] = useState(true)
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)

  // Create form state
  const [createOpen, setCreateOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [qnrId, setQnrId] = useState<string>('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Created result
  const [created, setCreated] = useState<{ share_url: string; link_token: string } | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    const fetches: Promise<any>[] = [
      fetch('/api/vendor-requests', { credentials: 'include' }).then(r => r.ok ? r.json() : []),
    ]
    if (workspace) {
      fetches.push(
        fetch(`/api/questionnaires?workspace_id=${workspace.id}`, { credentials: 'include' })
          .then(r => r.ok ? r.json() : [])
      )
    }
    Promise.all(fetches)
      .then(([reqs, qnrs]) => {
        setRequests(reqs ?? [])
        setQuestionnaires((qnrs ?? []).filter((q: Questionnaire) => q.status === 'completed'))
      })
      .catch(() => { setRequests([]); setQuestionnaires([]) })
      .finally(() => setLoading(false))
  }, [workspace])

  useEffect(() => { if (canEdit) load(); else setLoading(false) }, [canEdit, load])

  if (!canEdit) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Requests</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">You need editor or admin access to manage requests.</p>
        </div>
      </div>
    )
  }

  const onCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) { setError('Vendor email is required'); return }
    setSubmitting(true); setError(null)
    try {
      const body: Record<string, any> = { vendor_email: email.trim() }
      if (qnrId) body.questionnaire_id = parseInt(qnrId, 10)
      if (message.trim()) body.message = message.trim()

      const r = await fetch('/api/vendor-requests', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(d.detail || 'Failed to create request'); return }
      setCreated({ share_url: d.share_url, link_token: d.link_token })
      setToast({ message: 'Request created successfully', type: 'success' })
      load()
    } catch {
      setError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  const resetForm = () => {
    setCreateOpen(false); setEmail(''); setQnrId(''); setMessage('')
    setError(null); setCreated(null); setCopied(false)
  }

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(window.location.origin + url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setToast({ message: 'Failed to copy', type: 'error' })
    }
  }

  const updateStatus = async (id: number, status: string) => {
    const r = await fetch(`/api/vendor-requests/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    if (r.ok) load()
  }

  const qnrName = (id: number | null) => {
    if (!id) return '—'
    const q = questionnaires.find(q => q.id === id)
    return q ? q.filename : `#${id}`
  }

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Requests</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)] max-w-xl">
            Send a questionnaire or information request to a vendor and collect responses securely.
          </p>
        </div>
        {canAdmin && (
          <Button onClick={() => setCreateOpen(true)}>
            Create Request
          </Button>
        )}
      </div>

      {/* Requests table */}
      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-6 text-center text-[var(--tc-muted)]">Loading requests...</div>
        ) : requests.length === 0 ? (
          <div className="p-10 text-center">
            <div className="text-3xl mb-3">📨</div>
            <p className="text-sm font-medium text-[var(--tc-text)]">No requests yet</p>
            <p className="text-xs text-[var(--tc-muted)] mt-1 max-w-sm mx-auto">
              Create a request to send a questionnaire or information request to a vendor. You will get a secure link to share.
            </p>
            {canAdmin && (
              <Button className="mt-4" size="sm" onClick={() => setCreateOpen(true)}>
                Create First Request
              </Button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--tc-border)] text-[10px] uppercase tracking-wider text-[var(--tc-muted)]">
                  <th className="px-5 py-3 text-left font-semibold">Vendor</th>
                  <th className="px-5 py-3 text-left font-semibold">Questionnaire</th>
                  <th className="px-5 py-3 text-left font-semibold">Status</th>
                  <th className="px-5 py-3 text-left font-semibold">Created</th>
                  <th className="px-5 py-3 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {requests.map(req => (
                  <tr key={req.id} className="border-b border-[var(--tc-border)] last:border-0 hover:bg-white/[0.02] transition">
                    <td className="px-5 py-3">
                      <span className="text-[var(--tc-text)] font-medium">{req.vendor_email}</span>
                    </td>
                    <td className="px-5 py-3 text-[var(--tc-muted)]">
                      {qnrName(req.questionnaire_id)}
                    </td>
                    <td className="px-5 py-3">
                      {statusBadge(req.status)}
                    </td>
                    <td className="px-5 py-3 text-[var(--tc-muted)] text-xs">
                      {timeAgo(req.created_at)}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {req.link_token && (
                          <button
                            onClick={() => copyLink(`/vendor-response?token=${req.link_token}`)}
                            className="text-[11px] text-[var(--tc-primary)] hover:underline"
                          >
                            Copy Link
                          </button>
                        )}
                        {canAdmin && req.status !== 'completed' && (
                          <select
                            value=""
                            onChange={e => { if (e.target.value) updateStatus(req.id, e.target.value) }}
                            className="text-[11px] rounded border border-[var(--tc-border)] bg-transparent text-[var(--tc-muted)] px-1.5 py-0.5 cursor-pointer"
                          >
                            <option value="">Update...</option>
                            {req.status !== 'in_progress' && <option value="in_progress">In Progress</option>}
                            <option value="completed">Completed</option>
                          </select>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Create Request Modal */}
      <Modal isOpen={createOpen} title={created ? 'Request Created' : 'Create Request'} onClose={resetForm}>
          {created ? (
            <div className="space-y-4">
              <p className="text-sm text-[var(--tc-text)]">
                Your request has been created. Share this secure link with the vendor:
              </p>
              <div className="flex items-center gap-2 p-3 rounded-lg bg-white/5 border border-[var(--tc-border)]">
                <code className="flex-1 text-xs text-[var(--tc-text)] break-all">
                  {window.location.origin}{created.share_url}
                </code>
                <Button size="sm" variant="secondary" onClick={() => copyLink(created.share_url)}>
                  {copied ? 'Copied!' : 'Copy'}
                </Button>
              </div>
              <p className="text-xs text-[var(--tc-muted)]">
                The vendor can use this link to view the request and submit their response.
              </p>
              <div className="flex justify-end">
                <Button onClick={resetForm}>Done</Button>
              </div>
            </div>
          ) : (
            <form onSubmit={onCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">
                  Vendor Email <span className="text-red-400">*</span>
                </label>
                <Input
                  type="email"
                  placeholder="vendor@example.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">
                  Questionnaire
                </label>
                <select
                  value={qnrId}
                  onChange={e => setQnrId(e.target.value)}
                  className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
                >
                  <option value="">No questionnaire (general request)</option>
                  {questionnaires.map(q => (
                    <option key={q.id} value={q.id}>{q.filename}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">
                  Message <span className="text-[var(--tc-muted)]">(optional)</span>
                </label>
                <textarea
                  placeholder="Add context or instructions for the vendor..."
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  rows={3}
                  className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] resize-none focus:border-[var(--tc-primary)] focus:outline-none"
                />
              </div>

              {error && <p className="text-xs text-red-400">{error}</p>}

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="secondary" onClick={resetForm}>Cancel</Button>
                <Button type="submit" disabled={submitting}>
                  {submitting ? 'Creating...' : 'Create Link'}
                </Button>
              </div>
            </form>
          )}
        </Modal>

      {toast && (
        <Toast
          title={toast.type === 'success' ? 'Success' : 'Error'}
          message={toast.message}
          type={toast.type}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}
