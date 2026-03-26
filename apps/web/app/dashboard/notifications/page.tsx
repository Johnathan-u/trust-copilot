'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Modal } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  CATEGORY_META,
  getNotificationMeta,
  getNotificationTitle,
  getNotificationCategory,
  type NotificationCategory,
} from '@/lib/notification-labels'

/* ──────────────────── Types ──────────────────── */

type ActiveAlert = {
  severity: 'high' | 'medium' | 'low'
  title: string
  description: string
  metric: number
  type: string
}

type Policy = {
  id: number
  event_type: string
  enabled: boolean
  recipient_type: string
  recipient_value: string | null
  updated_at: string | null
}

type LogEntry = {
  id: number
  event_type: string
  channel: string
  recipient_email: string
  subject: string | null
  status: string
  error: string | null
  created_at: string | null
}

/* ──────────────────── Helpers ──────────────────── */

const RECIPIENT_TYPES = [
  { value: 'admins', label: 'Admins only' },
  { value: 'all', label: 'All members' },
  { value: 'role', label: 'Specific role' },
  { value: 'user', label: 'Specific user' },
]

function severityColor(severity: string): string {
  if (severity === 'high') return 'text-red-400'
  if (severity === 'medium') return 'text-amber-400'
  return 'text-[var(--tc-muted)]'
}

function severityBg(severity: string): string {
  if (severity === 'high') return 'border-red-500/30 bg-red-500/[0.06]'
  if (severity === 'medium') return 'border-amber-500/30 bg-amber-500/[0.06]'
  return 'border-[var(--tc-border)] bg-white/[0.02]'
}

function severityDot(severity: string): string {
  if (severity === 'high') return 'bg-red-400'
  if (severity === 'medium') return 'bg-amber-400'
  return 'bg-slate-400'
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

export default function ComplianceAlertsPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin

  const [activeAlerts, setActiveAlerts] = useState<ActiveAlert[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [eventTypes, setEventTypes] = useState<string[]>([])
  const [logEntries, setLogEntries] = useState<LogEntry[]>([])
  const [logTotal, setLogTotal] = useState(0)
  const [logPage, setLogPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [addEvt, setAddEvt] = useState('')
  const [addRecipType, setAddRecipType] = useState('admins')
  const [addRecipVal, setAddRecipVal] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/compliance-alerts/active', { credentials: 'include' }).then(r => r.ok ? r.json() : { alerts: [] }),
      fetch('/api/notifications/event-types', { credentials: 'include' }).then(r => r.ok ? r.json() : { event_types: [] }),
      fetch('/api/notifications/policies', { credentials: 'include' }).then(r => r.ok ? r.json() : { policies: [] }),
      fetch(`/api/notifications/log?page=${logPage}&page_size=25`, { credentials: 'include' }).then(r => r.ok ? r.json() : { entries: [], total: 0 }),
    ])
      .then(([alertsData, evtData, polData, logData]) => {
        setActiveAlerts(alertsData.alerts ?? [])
        setEventTypes(evtData.event_types ?? [])
        setPolicies(polData.policies ?? [])
        setLogEntries(logData.entries ?? [])
        setLogTotal(logData.total ?? 0)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [logPage])

  useEffect(() => { if (canAdmin) load(); else setLoading(false) }, [canAdmin, load])

  useEffect(() => {
    if (!canAdmin) return
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [canAdmin, load])

  const togglePolicy = async (p: Policy) => {
    await fetch(`/api/notifications/policies/${p.id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !p.enabled }),
    })
    load()
  }

  const deletePolicy = async (p: Policy) => {
    if (!confirm(`Remove alert rule "${getNotificationTitle(p.event_type)}"?`)) return
    await fetch(`/api/notifications/policies/${p.id}`, { method: 'DELETE', credentials: 'include' })
    load()
  }

  const addPolicy = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!addEvt) { setFormError('Select an event'); return }
    setSubmitting(true); setFormError(null)
    try {
      const r = await fetch('/api/notifications/policies', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type: addEvt, recipient_type: addRecipType, recipient_value: addRecipVal || undefined }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setFormError(d.detail || 'Failed'); return }
      setAddOpen(false); setAddEvt(''); setAddRecipType('admins'); setAddRecipVal('')
      load()
    } finally { setSubmitting(false) }
  }

  if (!canAdmin) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Alerts / Notifications</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">Admin access required to manage alerts.</p>
        </div>
      </div>
    )
  }

  const configuredEvents = new Set(policies.map(p => p.event_type))
  const availableEvents = eventTypes.filter(e => !configuredEvents.has(e))
  const logPages = Math.max(1, Math.ceil(logTotal / 25))

  const groupedAvailable: Record<NotificationCategory, string[]> = {
    compliance: availableEvents.filter(e => getNotificationCategory(e) === 'compliance'),
    system: availableEvents.filter(e => getNotificationCategory(e) === 'system'),
    team: availableEvents.filter(e => getNotificationCategory(e) === 'team'),
  }

  const groupedPolicies: Record<NotificationCategory, Policy[]> = {
    compliance: policies.filter(p => getNotificationCategory(p.event_type) === 'compliance'),
    system: policies.filter(p => getNotificationCategory(p.event_type) === 'system'),
    team: policies.filter(p => getNotificationCategory(p.event_type) === 'team'),
  }

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Alerts / Notifications</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">
          Stay informed about important changes in your compliance coverage, system events, and team activity.
        </p>
      </div>

      {loading ? (
        <Card className="p-6">
          <p className="text-[var(--tc-muted)]">Loading alerts...</p>
        </Card>
      ) : (
        <>
          {/* ── SECTION 1 — Active Alerts / Important Now ── */}
          <div>
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">Important Now</h2>
            {activeAlerts.length === 0 ? (
              <Card className="p-4">
                <div className="flex items-center gap-3">
                  <span className="text-lg">✅</span>
                  <p className="text-sm text-[var(--tc-muted)]">No active alerts. Your compliance coverage looks healthy.</p>
                </div>
              </Card>
            ) : (
              <div className="space-y-2">
                {activeAlerts.map((alert, i) => (
                  <div
                    key={i}
                    className={`rounded-lg border px-4 py-3 ${severityBg(alert.severity)}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className={`mt-1 inline-block h-2 w-2 rounded-full shrink-0 ${severityDot(alert.severity)}`} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-semibold ${severityColor(alert.severity)}`}>{alert.title}</span>
                          <span className={`text-[10px] uppercase font-medium px-1.5 py-0.5 rounded ${alert.severity === 'high' ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'}`}>
                            {alert.severity}
                          </span>
                        </div>
                        <p className="text-xs text-[var(--tc-muted)] mt-0.5">{alert.description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── SECTION 2 — Alert Rules ── */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--tc-text)]">Alert Rules</h2>
                <p className="text-xs text-[var(--tc-muted)] mt-0.5">Configure which events trigger email notifications</p>
              </div>
              <Button
                disabled={availableEvents.length === 0}
                onClick={() => {
                  setAddOpen(true)
                  setFormError(null)
                  const first = groupedAvailable.compliance[0] || groupedAvailable.system[0] || groupedAvailable.team[0] || ''
                  setAddEvt(first)
                }}
              >
                Add rule
              </Button>
            </div>

            {policies.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">No alert rules configured yet. Add a rule to start receiving notifications.</p>
            ) : (
              <div className="space-y-5">
                {(['compliance', 'system', 'team'] as const).map(cat => {
                  const catPolicies = groupedPolicies[cat]
                  if (catPolicies.length === 0) return null
                  const meta = CATEGORY_META[cat]
                  return (
                    <div key={cat}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm">{meta.icon}</span>
                        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--tc-muted)]">{meta.label}</span>
                      </div>
                      <div className="space-y-1">
                        {catPolicies.map(p => (
                          <div key={p.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                            <div className="flex items-center gap-3 min-w-0">
                              <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${p.enabled ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                              <div className="min-w-0">
                                <span className="text-sm text-[var(--tc-text)]">{getNotificationTitle(p.event_type)}</span>
                                <span className="text-xs text-[var(--tc-muted)] ml-2">
                                  → {p.recipient_type === 'admins' ? 'Admins' : p.recipient_type === 'all' ? 'All members' : `${p.recipient_type}: ${p.recipient_value || ''}`}
                                </span>
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                onClick={() => togglePolicy(p)}
                                className="text-xs px-2 py-1 rounded text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition"
                              >
                                {p.enabled ? 'Disable' : 'Enable'}
                              </button>
                              <button
                                onClick={() => deletePolicy(p)}
                                className="text-xs px-2 py-1 rounded text-[var(--tc-muted)] hover:text-red-400 transition"
                              >
                                Remove
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          {/* ── SECTION 4 — Recent Alert History ── */}
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">Recent Activity</h2>
            <p className="text-xs text-[var(--tc-muted)] mb-4">Notification delivery history</p>
            {logEntries.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">No notification history yet.</p>
            ) : (
              <>
                <div className="space-y-1">
                  {logEntries.map(entry => {
                    const meta = getNotificationMeta(entry.event_type)
                    return (
                      <div
                        key={entry.id}
                        className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${severityDot(meta.severity)}`} />
                          <div className="min-w-0">
                            <span className="text-sm text-[var(--tc-text)]">{meta.title}</span>
                            <span className="text-xs text-[var(--tc-muted)] ml-2">→ {entry.recipient_email}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          {entry.status === 'sent' ? (
                            <span className="text-[10px] uppercase font-medium text-emerald-400">sent</span>
                          ) : (
                            <span className="text-[10px] uppercase font-medium text-red-400" title={entry.error || ''}>failed</span>
                          )}
                          <span className="text-xs text-[var(--tc-muted)] w-16 text-right">{timeAgo(entry.created_at)}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
                {logPages > 1 && (
                  <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--tc-border)]">
                    <button
                      disabled={logPage <= 1}
                      onClick={() => setLogPage(logPage - 1)}
                      className="text-xs text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-30 transition"
                    >
                      ← Previous
                    </button>
                    <span className="text-xs text-[var(--tc-muted)]">Page {logPage} of {logPages}</span>
                    <button
                      disabled={logPage >= logPages}
                      onClick={() => setLogPage(logPage + 1)}
                      className="text-xs text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-30 transition"
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </Card>
        </>
      )}

      {/* ── SECTION 3 — Add Alert Rule Modal ── */}
      <Modal isOpen={addOpen} onClose={() => setAddOpen(false)} title="Add Alert Rule">
        <form onSubmit={addPolicy} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--tc-text)] mb-2">Event</label>
            <select
              className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
              value={addEvt}
              onChange={e => setAddEvt(e.target.value)}
            >
              {(['compliance', 'system', 'team'] as const).map(cat => {
                const items = groupedAvailable[cat]
                if (items.length === 0) return null
                return (
                  <optgroup key={cat} label={CATEGORY_META[cat].label}>
                    {items.map(et => (
                      <option key={et} value={et}>{getNotificationTitle(et)}</option>
                    ))}
                  </optgroup>
                )
              })}
            </select>
            {addEvt && (
              <p className="mt-1.5 text-xs text-[var(--tc-muted)]">{getNotificationMeta(addEvt).description}</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--tc-text)] mb-2">Recipients</label>
            <select
              className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
              value={addRecipType}
              onChange={e => setAddRecipType(e.target.value)}
            >
              {RECIPIENT_TYPES.map(rt => <option key={rt.value} value={rt.value}>{rt.label}</option>)}
            </select>
          </div>
          {(addRecipType === 'role' || addRecipType === 'user') && (
            <div>
              <label className="block text-sm font-medium text-[var(--tc-text)] mb-2">
                {addRecipType === 'role' ? 'Role name' : 'User email or ID'}
              </label>
              <input
                className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
                value={addRecipVal}
                onChange={e => setAddRecipVal(e.target.value)}
                placeholder={addRecipType === 'role' ? 'e.g. editor' : 'e.g. user@company.com'}
              />
            </div>
          )}
          {formError && <p className="text-sm text-[var(--tc-danger)]">{formError}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Adding...' : 'Add Rule'}</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
