'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ──────────────────── Types ──────────────────── */

type AuditEvent = {
  id: number
  occurred_at: string | null
  action: string
  user_id: number | null
  email: string | null
  resource_type: string | null
  resource_id: string | null
  details: string | null
}

/* ──────────────────── Event metadata ──────────────────── */

type Category = 'user' | 'system' | 'ai' | 'admin' | 'integration'
type Severity = 'high' | 'medium' | 'low' | 'routine'

type EventConfig = {
  label: string
  category: Category
  severity: Severity
}

const EVENT_CONFIG: Record<string, EventConfig> = {
  'auth.login':                   { label: 'User logged in',              category: 'user',        severity: 'routine' },
  'auth.logout':                  { label: 'User logged out',             category: 'user',        severity: 'routine' },
  'auth.register':                { label: 'Account registered',          category: 'user',        severity: 'low' },
  'auth.email_verified':          { label: 'Email verified',              category: 'user',        severity: 'low' },
  'auth.login_failed':            { label: 'Login failed',                category: 'user',        severity: 'high' },
  'auth.password_changed':        { label: 'Password changed',            category: 'user',        severity: 'medium' },
  'auth.change_password_failed':  { label: 'Password change failed',      category: 'user',        severity: 'high' },
  'auth.reset_requested':         { label: 'Password reset requested',    category: 'user',        severity: 'low' },
  'auth.password_reset':          { label: 'Password reset completed',    category: 'user',        severity: 'medium' },
  'auth.workspace_switch':        { label: 'Switched workspace',          category: 'user',        severity: 'routine' },
  'auth.sessions_revoked_others': { label: 'Other sessions revoked',      category: 'user',        severity: 'medium' },
  'auth.oauth_failed':            { label: 'OAuth login failed',          category: 'user',        severity: 'high' },
  'auth.sso_failed':              { label: 'SSO login failed',            category: 'user',        severity: 'high' },
  'auth.idme_failed':             { label: 'ID.me verification failed',   category: 'user',        severity: 'high' },
  'auth.invite_created':          { label: 'Invitation sent',             category: 'admin',       severity: 'low' },
  'auth.invite_revoked':          { label: 'Invitation revoked',          category: 'admin',       severity: 'low' },
  'auth.invite_accepted':         { label: 'Invitation accepted',         category: 'user',        severity: 'low' },
  'auth.invite_accepted_new_user':{ label: 'New user joined via invite',  category: 'user',        severity: 'low' },
  'auth.role_changed':            { label: 'User role changed',           category: 'admin',       severity: 'medium' },
  'auth.member_removed':          { label: 'Member removed',              category: 'admin',       severity: 'medium' },
  'auth.member_suspended':        { label: 'Member suspended',            category: 'admin',       severity: 'high' },
  'auth.member_unsuspended':      { label: 'Member unsuspended',          category: 'admin',       severity: 'medium' },
  'auth.sessions_revoked_by_admin':{ label: 'Sessions revoked by admin', category: 'admin',       severity: 'medium' },
  'auth.mfa_setup_started':       { label: 'MFA setup started',           category: 'user',        severity: 'low' },
  'auth.mfa_enabled':             { label: 'MFA enabled',                 category: 'user',        severity: 'medium' },
  'auth.mfa_disabled':            { label: 'MFA disabled',                category: 'user',        severity: 'high' },
  'auth.mfa_required':            { label: 'MFA verification required',   category: 'user',        severity: 'routine' },
  'auth.mfa_verify_failed':       { label: 'MFA verification failed',     category: 'user',        severity: 'high' },
  'auth.mfa_confirm_failed':      { label: 'MFA confirmation failed',     category: 'user',        severity: 'high' },
  'auth.mfa_recovery_used':       { label: 'MFA recovery code used',      category: 'user',        severity: 'high' },
  'auth.mfa_disable_failed':      { label: 'MFA disable failed',          category: 'user',        severity: 'high' },
  'auth.mfa_admin_reset':         { label: 'MFA reset by admin',          category: 'admin',       severity: 'medium' },
  'role.created':                 { label: 'Role created',                category: 'admin',       severity: 'low' },
  'role.updated':                 { label: 'Role updated',                category: 'admin',       severity: 'low' },
  'role.deleted':                 { label: 'Role deleted',                category: 'admin',       severity: 'medium' },
  'document.soft_delete':         { label: 'Document deleted',            category: 'system',      severity: 'medium' },
  'document.delete_preview':      { label: 'Document deletion previewed', category: 'system',      severity: 'routine' },
  'document.restore':             { label: 'Document restored',           category: 'system',      severity: 'low' },
  'document.metadata_update':     { label: 'Document metadata updated',   category: 'system',      severity: 'routine' },
  'job.completed':                { label: 'Processing completed',        category: 'system',      severity: 'low' },
  'job.failed':                   { label: 'Processing failed',           category: 'system',      severity: 'high' },
  'automation.enabled':           { label: 'Automation enabled',          category: 'admin',       severity: 'low' },
  'automation.disabled':          { label: 'Automation disabled',         category: 'admin',       severity: 'low' },
  'automation.run_started':       { label: 'Automation started',          category: 'system',      severity: 'low' },
  'automation.run_completed':     { label: 'Automation completed',        category: 'system',      severity: 'low' },
  'automation.run_needs_review':  { label: 'Review required',             category: 'ai',          severity: 'high' },
  'notification.policy_created':  { label: 'Alert rule created',          category: 'admin',       severity: 'low' },
  'notification.policy_updated':  { label: 'Alert rule updated',          category: 'admin',       severity: 'low' },
  'notification.policy_deleted':  { label: 'Alert rule deleted',          category: 'admin',       severity: 'low' },
  'gmail.connected':              { label: 'Gmail connected',             category: 'integration', severity: 'low' },
  'gmail.disconnected':           { label: 'Gmail disconnected',          category: 'integration', severity: 'medium' },
  'gmail.label_approved':         { label: 'Gmail label approved',        category: 'integration', severity: 'low' },
  'gmail.label_revoked':          { label: 'Gmail label removed',         category: 'integration', severity: 'low' },
  'gmail.evidence_ingested':      { label: 'Email evidence ingested',     category: 'integration', severity: 'low' },
  'gmail.attachment_ingested':    { label: 'Email attachment ingested',   category: 'integration', severity: 'low' },
  'gmail.suggestion_approved':    { label: 'Gmail suggestion approved',   category: 'integration', severity: 'low' },
  'gmail.suggestion_dismissed':   { label: 'Gmail suggestion dismissed',  category: 'integration', severity: 'routine' },
  'slack.connected':              { label: 'Slack connected',             category: 'integration', severity: 'low' },
  'slack.configured':             { label: 'Slack configured',            category: 'integration', severity: 'low' },
  'slack.disconnected':           { label: 'Slack disconnected',          category: 'integration', severity: 'medium' },
  'slack.ingest_channel_approved':{ label: 'Slack channel approved',      category: 'integration', severity: 'low' },
  'slack.ingest_channel_revoked': { label: 'Slack channel removed',       category: 'integration', severity: 'low' },
  'slack.evidence_ingested':      { label: 'Slack evidence ingested',     category: 'integration', severity: 'low' },
  'slack.suggestion_approved':    { label: 'Slack suggestion approved',   category: 'integration', severity: 'low' },
  'slack.suggestion_dismissed':   { label: 'Slack suggestion dismissed',  category: 'integration', severity: 'routine' },
  'trust_request.update':         { label: 'Trust request updated',       category: 'system',      severity: 'low' },
  'trust_request.soft_delete':    { label: 'Trust request deleted',       category: 'system',      severity: 'medium' },
  'trust_request.restore':        { label: 'Trust request restored',      category: 'system',      severity: 'low' },
  'trust_request.note_added':     { label: 'Note added to request',       category: 'system',      severity: 'routine' },
  'trust_request.reply_added':    { label: 'Reply added to request',      category: 'system',      severity: 'routine' },
  'trust_request.delete_preview': { label: 'Request deletion previewed',  category: 'system',      severity: 'routine' },
  'trust_request.metadata_update':{ label: 'Request metadata updated',    category: 'system',      severity: 'routine' },
  'dashboard.card_created':       { label: 'Dashboard card created',      category: 'admin',       severity: 'routine' },
  'dashboard.card_updated':       { label: 'Dashboard card updated',      category: 'admin',       severity: 'routine' },
  'dashboard.card_deleted':       { label: 'Dashboard card deleted',      category: 'admin',       severity: 'routine' },
  'dashboard.layout_reordered':   { label: 'Dashboard layout changed',    category: 'admin',       severity: 'routine' },
  'ai_governance.settings.updated':{ label: 'AI governance updated',      category: 'ai',          severity: 'medium' },
  'compliance.evidence.verified': { label: 'Evidence verified',           category: 'ai',          severity: 'low' },
  'compliance.control.verified':  { label: 'Control verified',            category: 'ai',          severity: 'low' },
  'compliance.mapping.confirmed': { label: 'Mapping confirmed',           category: 'ai',          severity: 'low' },
  'compliance.mapping.overridden':{ label: 'Mapping overridden',          category: 'ai',          severity: 'medium' },
}

const CATEGORY_META: Record<Category, { label: string; icon: string; color: string }> = {
  user:        { label: 'User',        icon: '👤', color: 'bg-blue-500/15 text-blue-400' },
  system:      { label: 'System',      icon: '⚙️', color: 'bg-slate-500/15 text-slate-400' },
  ai:          { label: 'AI',          icon: '🤖', color: 'bg-purple-500/15 text-purple-400' },
  admin:       { label: 'Admin',       icon: '🔑', color: 'bg-amber-500/15 text-amber-400' },
  integration: { label: 'Integration', icon: '🔗', color: 'bg-teal-500/15 text-teal-400' },
}

const CATEGORY_FILTERS: { value: string; label: string }[] = [
  { value: '',            label: 'All activity' },
  { value: 'cat:user',    label: 'User activity' },
  { value: 'cat:system',  label: 'System processing' },
  { value: 'cat:ai',      label: 'AI & compliance' },
  { value: 'cat:admin',   label: 'Admin actions' },
  { value: 'cat:integration', label: 'Integrations' },
  { value: 'auth.login',  label: 'Logins only' },
  { value: 'job.',        label: 'Jobs only' },
]

const TIME_FILTERS = [
  { value: 24,  label: 'Last 24 hours' },
  { value: 168, label: 'Last 7 days' },
  { value: 720, label: 'Last 30 days' },
]

/* ──────────────────── Detail formatting ──────────────────── */

function parseDetails(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

function formatDetails(action: string, raw: string | null): string {
  const d = parseDetails(raw)
  if (!d) return ''

  const kind = (d.kind as string) || ''
  const qnrName = (d.questionnaire as string) || ''
  const docName = (d.document as string) || (d.filename as string) || ''
  const total = d.total as number | undefined
  const insuffCount = d.insufficient_count as number | undefined
  const email = (d.email as string) || (d.target_email as string) || ''
  const role = (d.role as string) || (d.new_role as string) || ''
  const reason = (d.reason as string) || ''
  const eventType = (d.event_type as string) || ''
  const qnrId = d.questionnaire_id as number | undefined
  const channel = (d.channel_name as string) || (d.channel_id as string) || ''

  if (action === 'job.completed' || action === 'job.failed') {
    if (kind === 'parse_questionnaire' && qnrId) return `Processed questionnaire #${qnrId}`
    if (kind === 'generate_answers' && qnrName) {
      let s = `Generated answers for ${qnrName}`
      if (total) s += ` — ${total} questions`
      return s
    }
    if (kind) return kind.replace(/_/g, ' ')
  }

  if (action === 'automation.run_needs_review') {
    let s = qnrName ? `Review needed: ${qnrName}` : 'Review required'
    if (total && insuffCount) s += ` — ${total} questions, ${insuffCount} insufficient`
    return s
  }

  if (action === 'automation.run_completed') {
    let s = qnrName ? `Completed: ${qnrName}` : 'Automation completed'
    if (total) s += ` — ${total} questions processed`
    return s
  }

  if (action.startsWith('auth.role_changed') && email) {
    return role ? `${email} → ${role}` : email
  }

  if ((action === 'auth.member_removed' || action === 'auth.member_suspended' || action === 'auth.member_unsuspended') && email) {
    return email
  }

  if (action === 'auth.invite_created' && email) return `Invited ${email}`
  if (action === 'auth.login_failed' && reason) return reason
  if (action === 'auth.mfa_verify_failed' || action === 'auth.mfa_confirm_failed') return reason || 'Verification failed'

  if (action.startsWith('notification.policy') && eventType) return eventType.replace(/[._]/g, ' ')

  if (action === 'document.soft_delete' && docName) return docName
  if (action === 'document.restore' && docName) return docName

  if ((action === 'slack.connected' || action === 'slack.configured') && channel) return `#${channel}`
  if ((action === 'gmail.connected') && email) return email

  const changes = d.changes as Record<string, unknown> | undefined
  if (changes) {
    const keys = Object.keys(changes)
    if (keys.length > 0) return keys.map(k => k.replace(/_/g, ' ')).join(', ') + ' updated'
  }

  return ''
}

/* ──────────────────── Helpers ──────────────────── */

function getConfig(action: string): EventConfig {
  if (EVENT_CONFIG[action]) return EVENT_CONFIG[action]
  if (action.startsWith('ai_mapping.')) {
    if (action.includes('.approved')) return { label: 'AI mapping approved', category: 'ai', severity: 'low' }
    if (action.includes('.rejected')) return { label: 'AI mapping rejected', category: 'ai', severity: 'low' }
    if (action.includes('.suggest')) return { label: 'AI suggestion generated', category: 'ai', severity: 'routine' }
    if (action.includes('.created')) return { label: 'AI mapping created', category: 'ai', severity: 'low' }
    if (action.includes('.deleted')) return { label: 'AI mapping deleted', category: 'ai', severity: 'low' }
    return { label: action.split('.').pop()?.replace(/_/g, ' ') || action, category: 'ai', severity: 'routine' }
  }
  if (action.startsWith('compliance.')) return { label: action.replace('compliance.', '').replace(/[._]/g, ' '), category: 'ai', severity: 'low' }
  const prefix = action.split('.')[0]
  const cat: Category = prefix === 'auth' ? 'user' : prefix === 'slack' || prefix === 'gmail' ? 'integration' : 'system'
  return { label: action.replace(/[._]/g, ' '), category: cat, severity: 'routine' }
}

function severityDot(sev: Severity): string {
  if (sev === 'high') return 'bg-red-400'
  if (sev === 'medium') return 'bg-amber-400'
  if (sev === 'low') return 'bg-emerald-400'
  return 'bg-slate-500'
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

function actorDisplay(ev: AuditEvent): string {
  if (ev.email) return ev.email
  if (ev.action.startsWith('job.') || ev.action.startsWith('automation.')) return 'System'
  return '—'
}

/* ──────────────────── Component ──────────────────── */

export default function AuditPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [since, setSince] = useState(168)
  const [expanded, setExpanded] = useState<number | null>(null)
  const pageSize = 50

  const load = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      since_hours: String(since),
    })
    if (filter && !filter.startsWith('cat:')) {
      params.set('action', filter)
    }
    fetch(`/api/audit/events?${params}`, { credentials: 'include' })
      .then(r => r.ok ? r.json() : { events: [], total: 0 })
      .then(d => {
        let rows: AuditEvent[] = d.events ?? []
        if (filter.startsWith('cat:')) {
          const cat = filter.replace('cat:', '') as Category
          rows = rows.filter(ev => getConfig(ev.action).category === cat)
        }
        setEvents(rows)
        setTotal(filter.startsWith('cat:') ? rows.length : (d.total ?? 0))
      })
      .catch(() => { setEvents([]); setTotal(0) })
      .finally(() => setLoading(false))
  }, [page, since, filter])

  useEffect(() => { if (canAdmin) load(); else setLoading(false) }, [canAdmin, load])

  useEffect(() => { setPage(1) }, [filter, since])

  if (!canAdmin) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">System Activity</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">Admin access required.</p>
        </div>
      </div>
    )
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="min-w-0 space-y-6 pb-8">
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">System Activity</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">
          Track important user, system, and AI activity across your workspace.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <select
          value={filter}
          onChange={e => setFilter(e.target.value)}
          className="rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
        >
          {CATEGORY_FILTERS.map(f => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <select
          value={since}
          onChange={e => setSince(Number(e.target.value))}
          className="rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
        >
          {TIME_FILTERS.map(f => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <span className="text-xs text-[var(--tc-muted)] ml-auto">{total} events</span>
      </div>

      {/* Event list */}
      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-6"><p className="text-[var(--tc-muted)]">Loading...</p></div>
        ) : events.length === 0 ? (
          <div className="p-6"><p className="text-[var(--tc-muted)]">No activity found for this filter and time range.</p></div>
        ) : (
          <div>
            {events.map(ev => {
              const cfg = getConfig(ev.action)
              const catMeta = CATEGORY_META[cfg.category]
              const detail = formatDetails(ev.action, ev.details)
              const isExpanded = expanded === ev.id
              const actor = actorDisplay(ev)

              return (
                <div key={ev.id} className="border-b border-[var(--tc-border)] last:border-b-0">
                  <button
                    onClick={() => setExpanded(isExpanded ? null : ev.id)}
                    className="w-full text-left px-5 py-3 hover:bg-white/[0.02] transition flex items-start gap-3"
                  >
                    {/* Severity dot */}
                    <span className={`mt-2 inline-block h-2 w-2 rounded-full shrink-0 ${severityDot(cfg.severity)}`} />

                    {/* Main content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-[var(--tc-text)]">{cfg.label}</span>
                        <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded ${catMeta.color}`}>
                          {catMeta.label}
                        </span>
                      </div>
                      {detail && (
                        <p className="text-xs text-[var(--tc-muted)] mt-0.5 truncate">{detail}</p>
                      )}
                    </div>

                    {/* Actor */}
                    <div className="shrink-0 text-right">
                      <p className="text-xs text-[var(--tc-muted)]">{actor}</p>
                      <p className="text-[11px] text-[var(--tc-muted)] opacity-60">{timeAgo(ev.occurred_at)}</p>
                    </div>

                    {/* Expand indicator */}
                    <span className="mt-1 text-[var(--tc-muted)] text-xs shrink-0">{isExpanded ? '▾' : '▸'}</span>
                  </button>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="px-5 pb-4 pl-10 space-y-1.5">
                      <div className="rounded-lg border border-[var(--tc-border)] bg-[rgba(0,0,0,0.15)] p-3 text-xs space-y-1">
                        <div className="flex gap-8">
                          <div>
                            <span className="text-[var(--tc-muted)]">Event: </span>
                            <span className="text-[var(--tc-text)] font-mono">{ev.action}</span>
                          </div>
                          <div>
                            <span className="text-[var(--tc-muted)]">Time: </span>
                            <span className="text-[var(--tc-text)]">
                              {ev.occurred_at ? new Date(ev.occurred_at).toLocaleString() : '—'}
                            </span>
                          </div>
                        </div>
                        <div className="flex gap-8">
                          {ev.email && (
                            <div>
                              <span className="text-[var(--tc-muted)]">User: </span>
                              <span className="text-[var(--tc-text)]">{ev.email}</span>
                            </div>
                          )}
                          {ev.user_id && (
                            <div>
                              <span className="text-[var(--tc-muted)]">User ID: </span>
                              <span className="text-[var(--tc-text)]">{ev.user_id}</span>
                            </div>
                          )}
                          {ev.resource_type && (
                            <div>
                              <span className="text-[var(--tc-muted)]">Resource: </span>
                              <span className="text-[var(--tc-text)]">{ev.resource_type}{ev.resource_id ? ` #${ev.resource_id}` : ''}</span>
                            </div>
                          )}
                        </div>
                        {ev.details && (
                          <div className="mt-2 pt-2 border-t border-[var(--tc-border)]">
                            <span className="text-[var(--tc-muted)]">Details:</span>
                            <pre className="mt-1 text-[var(--tc-text)] whitespace-pre-wrap break-all font-mono text-[11px] max-h-32 overflow-y-auto">
                              {(() => {
                                try { return JSON.stringify(JSON.parse(ev.details), null, 2) } catch { return ev.details }
                              })()}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {/* Pagination */}
      {totalPages > 1 && !filter.startsWith('cat:') && (
        <div className="flex items-center justify-between">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="text-xs text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-30 transition"
          >
            ← Previous
          </button>
          <span className="text-xs text-[var(--tc-muted)]">Page {page} of {totalPages}</span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            className="text-xs text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-30 transition"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}
