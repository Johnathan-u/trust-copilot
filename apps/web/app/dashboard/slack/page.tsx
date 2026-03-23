'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, Modal } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ──────────────────── Types ──────────────────── */

type SlackStatus = {
  connected: boolean
  enabled?: boolean
  channel_id?: string
  channel_name?: string
  event_types?: string[]
  updated_at?: string
}

type Channel = { id: string; name: string }
type IngestChannel = { id: number; channel_id: string; channel_name: string | null; enabled: boolean; created_at: string | null }
type IngestEvidence = { id: number; title: string; source_metadata: Record<string, string> | null; created_at: string | null }
type IngestSuggestion = { id: number; evidence_id: number; control_id: number; confidence: number | null; status: string; created_at: string | null }

/* ──────────────────── Event metadata ──────────────────── */

type EventMeta = {
  label: string
  category: 'compliance' | 'system' | 'team'
  severity?: 'high' | 'medium'
  preview?: string
}

const EVENT_META: Record<string, EventMeta> = {
  'compliance.coverage_drop':    { label: 'Coverage dropped',                 category: 'compliance', severity: 'high',   preview: '⚠️ Coverage dropped to 68% — 14 questions lack sufficient evidence' },
  'compliance.high_insufficient': { label: 'High insufficient-answer rate',   category: 'compliance', severity: 'high',   preview: '⚠️ 12 questions marked insufficient in HIPAA workspace' },
  'compliance.blind_spot':       { label: 'New blind spot detected',          category: 'compliance', severity: 'medium', preview: '🔍 New blind spot: Risk Assessment — 4 questions have no evidence' },
  'compliance.weak_evidence':    { label: 'Weak evidence detected',           category: 'compliance', severity: 'medium', preview: '📉 Weak evidence in Vendor Risk — avg confidence 38%' },
  'questionnaire.uploaded':      { label: 'Questionnaire uploaded',           category: 'system',     preview: '📋 New questionnaire uploaded: "SOC 2 Security Review"' },
  'questionnaire.generated':     { label: 'Questionnaire processed',          category: 'system',     preview: '✅ Questionnaire processed — 42 answers generated' },
  'export.completed':            { label: 'Export completed',                 category: 'system',     preview: '📦 Export completed and ready for download' },
  'document.indexed':            { label: 'Document processed',               category: 'system',     preview: '📄 New document indexed: "Information Security Policy.pdf"' },
  'member.invited':              { label: 'Member invited',                   category: 'team',       preview: '👤 jane@company.com was invited to the workspace' },
  'member.joined':               { label: 'Member joined',                    category: 'team',       preview: '👤 jane@company.com joined the workspace' },
  'member.removed':              { label: 'Member removed',                   category: 'team',       preview: '👤 jane@company.com was removed from the workspace' },
  'member.suspended':            { label: 'Member suspended',                 category: 'team',       preview: '⚠️ jane@company.com was suspended' },
  'member.role_changed':         { label: 'Role changed',                     category: 'team',       preview: '🔑 jane@company.com role changed to Editor' },
  'role.created':                { label: 'Role created',                     category: 'team',       preview: '🔑 New role created: "Auditor"' },
  'role.updated':                { label: 'Role updated',                     category: 'team',       preview: '🔑 Role "Editor" permissions updated' },
  'role.deleted':                { label: 'Role deleted',                     category: 'team',       preview: '🔑 Role "Temp Reviewer" deleted' },
}

const CATEGORIES = [
  { key: 'compliance' as const, label: 'Compliance Alerts', icon: '🛡️', description: 'Coverage changes, blind spots, and evidence gaps' },
  { key: 'system' as const,     label: 'System Events',     icon: '⚙️', description: 'Questionnaire processing, exports, and documents' },
  { key: 'team' as const,       label: 'Team Activity',     icon: '👥', description: 'Member and role changes' },
]

function eventLabel(evt: string): string {
  return EVENT_META[evt]?.label ?? evt.replace(/[._]/g, ' ')
}

function severityBadge(severity?: 'high' | 'medium') {
  if (!severity) return null
  return (
    <span className={`ml-2 text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${
      severity === 'high'
        ? 'bg-red-500/15 text-red-400'
        : 'bg-amber-500/15 text-amber-400'
    }`}>
      {severity}
    </span>
  )
}

/* ──────────────────── Component ──────────────────── */

export default function SlackPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const [status, setStatus] = useState<SlackStatus>({ connected: false })
  const [channels, setChannels] = useState<Channel[]>([])
  const [allEvents, setAllEvents] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [connectOpen, setConnectOpen] = useState(false)
  const [token, setToken] = useState('')
  const [channelId, setChannelId] = useState('')
  const [channelName, setChannelName] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<string | null>(null)
  const [tab, setTab] = useState<'notifications' | 'ingest'>('notifications')
  const [ingestChannels, setIngestChannels] = useState<IngestChannel[]>([])
  const [ingestEvidence, setIngestEvidence] = useState<IngestEvidence[]>([])
  const [ingestSuggestions, setIngestSuggestions] = useState<IngestSuggestion[]>([])
  const [addChOpen, setAddChOpen] = useState(false)
  const [addChId, setAddChId] = useState('')
  const [addChName, setAddChName] = useState('')
  const [ingestRunning, setIngestRunning] = useState<number | null>(null)
  const [ingestResult, setIngestResult] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/slack/status', { credentials: 'include' }),
      fetch('/api/notifications/event-types', { credentials: 'include' }),
    ])
      .then(([r1, r2]) => Promise.all([r1.ok ? r1.json() : { connected: false }, r2.ok ? r2.json() : { event_types: [] }]))
      .then(([d1, d2]) => {
        setStatus(d1)
        setAllEvents(d2.event_types ?? [])
        if (d1.connected) {
          fetch('/api/slack/channels', { credentials: 'include' })
            .then(r => r.ok ? r.json() : { channels: [] })
            .then(d => setChannels(d.channels ?? []))
            .catch(() => {})
          fetch('/api/slack/ingest/channels', { credentials: 'include' })
            .then(r => r.ok ? r.json() : { channels: [] })
            .then(d => setIngestChannels(d.channels ?? []))
            .catch(() => {})
          fetch('/api/slack/ingest/evidence?page_size=20', { credentials: 'include' })
            .then(r => r.ok ? r.json() : { evidence: [] })
            .then(d => setIngestEvidence(d.evidence ?? []))
            .catch(() => {})
          fetch('/api/slack/ingest/suggestions?status=pending', { credentials: 'include' })
            .then(r => r.ok ? r.json() : { suggestions: [] })
            .then(d => setIngestSuggestions(d.suggestions ?? []))
            .catch(() => {})
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { if (canAdmin) load(); else setLoading(false) }, [canAdmin, load])

  const connect = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token.trim() || !channelId.trim()) { setError('Token and channel are required'); return }
    setSubmitting(true); setError(null)
    try {
      const evts = selectedEvents.length > 0 ? selectedEvents : undefined
      const r = await fetch('/api/slack/connect', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot_token: token, channel_id: channelId, channel_name: channelName, event_types: evts }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(d.detail || 'Failed to connect'); return }
      setConnectOpen(false); setToken(''); setChannelId(''); setChannelName(''); setSelectedEvents([])
      load()
    } finally { setSubmitting(false) }
  }

  const disconnect = async () => {
    if (!confirm('Disconnect Slack? Notifications will stop.')) return
    await fetch('/api/slack/disconnect', { method: 'DELETE', credentials: 'include' })
    load()
  }

  const toggleEnabled = async () => {
    await fetch('/api/slack/configure', {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !status.enabled }),
    })
    load()
  }

  const updateEvents = async (events: string[]) => {
    await fetch('/api/slack/configure', {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_types: events }),
    })
    load()
  }

  const changeChannel = async (chId: string) => {
    const ch = channels.find(c => c.id === chId)
    await fetch('/api/slack/configure', {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel_id: chId, channel_name: ch?.name || '' }),
    })
    load()
  }

  const sendTest = async () => {
    setTestResult(null)
    const r = await fetch('/api/slack/test', { method: 'POST', credentials: 'include' })
    const d = await r.json().catch(() => ({}))
    setTestResult(r.ok ? 'Test message sent!' : `Failed: ${d.detail || 'unknown error'}`)
  }

  const addIngestChannel = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!addChId.trim()) { setError('Channel ID required'); return }
    setSubmitting(true); setError(null)
    try {
      const r = await fetch('/api/slack/ingest/channels', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel_id: addChId.trim(), channel_name: addChName.trim() || undefined }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(d.detail || 'Failed'); return }
      setAddChOpen(false); setAddChId(''); setAddChName(''); load()
    } finally { setSubmitting(false) }
  }

  const removeIngestChannel = async (id: number) => {
    if (!confirm('Remove this channel from evidence ingestion?')) return
    await fetch(`/api/slack/ingest/channels/${id}`, { method: 'DELETE', credentials: 'include' })
    load()
  }

  const runIngest = async (recId: number) => {
    setIngestRunning(recId); setIngestResult(null)
    try {
      const r = await fetch(`/api/slack/ingest/run/${recId}?limit=20`, { method: 'POST', credentials: 'include' })
      const d = await r.json().catch(() => ({}))
      setIngestResult(r.ok ? `Ingested ${d.ingested ?? 0}, skipped ${d.skipped ?? 0}` : `Error: ${d.detail || 'failed'}`)
      load()
    } finally { setIngestRunning(null) }
  }

  const reviewSuggestion = async (id: number, action: 'approve' | 'dismiss') => {
    await fetch(`/api/slack/ingest/suggestions/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    load()
  }

  /* ── Helpers for grouped event rendering ── */

  function groupedEvents(eventList: string[]) {
    return CATEGORIES.map(cat => ({
      ...cat,
      events: eventList.filter(e => (EVENT_META[e]?.category ?? 'system') === cat.key),
    })).filter(g => g.events.length > 0)
  }

  const currentEvents = status.event_types || []
  const hasNoSelection = currentEvents.length === 0

  /* ── Event checkbox group ── */
  function EventCheckboxGroup({
    events,
    checked,
    onChange,
    size = 'normal',
  }: {
    events: string[]
    checked: string[]
    onChange: (next: string[]) => void
    size?: 'normal' | 'compact'
  }) {
    const groups = groupedEvents(events)
    return (
      <div className="space-y-4">
        {groups.map(g => (
          <div key={g.key}>
            <div className="flex items-center gap-2 mb-2">
              <span className={size === 'compact' ? 'text-xs' : 'text-sm'}>{g.icon}</span>
              <span className={`font-semibold uppercase tracking-wide text-[var(--tc-muted)] ${size === 'compact' ? 'text-[10px]' : 'text-xs'}`}>
                {g.label}
              </span>
            </div>
            <div className={`grid gap-1 ${size === 'compact' ? 'grid-cols-2' : 'grid-cols-1'}`}>
              {g.events.map(evt => {
                const meta = EVENT_META[evt]
                const isChecked = checked.includes(evt)
                return (
                  <label
                    key={evt}
                    className={`flex items-center gap-2.5 rounded-lg border px-3 cursor-pointer transition ${
                      size === 'compact' ? 'py-1.5' : 'py-2'
                    } ${
                      isChecked
                        ? 'border-[rgba(91,124,255,0.3)] bg-[rgba(91,124,255,0.06)]'
                        : 'border-[var(--tc-border)] hover:bg-white/[0.02]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => {
                        const next = isChecked ? checked.filter(e => e !== evt) : [...checked, evt]
                        onChange(next)
                      }}
                      className="h-3.5 w-3.5 shrink-0"
                    />
                    <span className={`text-[var(--tc-text)] ${size === 'compact' ? 'text-xs' : 'text-sm'}`}>
                      {eventLabel(evt)}
                    </span>
                    {meta?.severity && severityBadge(meta.severity)}
                  </label>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    )
  }

  if (!canAdmin) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Slack Integration</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">Admin access required.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-w-0 space-y-6 pb-8">
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Slack Integration</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">
          Send compliance alerts and system notifications to your Slack workspace.
        </p>
      </div>

      {status.connected && (
        <div className="flex gap-2">
          <button onClick={() => setTab('notifications')} className={`px-4 py-2 rounded-lg text-sm font-medium transition ${tab === 'notifications' ? 'bg-[rgba(91,124,255,0.14)] text-[var(--tc-text)] border border-[rgba(91,124,255,0.22)]' : 'text-[var(--tc-muted)] hover:text-[var(--tc-text)] border border-transparent'}`}>
            Notifications
          </button>
          <button onClick={() => setTab('ingest')} className={`px-4 py-2 rounded-lg text-sm font-medium transition ${tab === 'ingest' ? 'bg-[rgba(91,124,255,0.14)] text-[var(--tc-text)] border border-[rgba(91,124,255,0.22)]' : 'text-[var(--tc-muted)] hover:text-[var(--tc-text)] border border-transparent'}`}>
            Evidence Ingest
          </button>
        </div>
      )}

      {loading ? (
        <Card className="p-6"><p className="text-[var(--tc-muted)]">Loading...</p></Card>
      ) : !status.connected ? (
        <Card className="p-6">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-2xl">💬</span>
            <div>
              <h2 className="text-base font-semibold text-[var(--tc-text)]">Connect Slack</h2>
              <p className="text-sm text-[var(--tc-muted)]">
                Receive compliance alerts, system notifications, and team activity updates in a Slack channel.
              </p>
            </div>
          </div>
          <Button onClick={() => { setConnectOpen(true); setError(null); setSelectedEvents([]) }}>Connect Slack</Button>
        </Card>
      ) : tab === 'notifications' ? (
        <div className="space-y-6">
          {/* Connection status */}
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={`inline-block h-2.5 w-2.5 rounded-full ${status.enabled ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                <div>
                  <h2 className="text-sm font-semibold text-[var(--tc-text)]">
                    {status.enabled ? 'Connected & Active' : 'Connected — Paused'}
                  </h2>
                  <p className="text-xs text-[var(--tc-muted)]">
                    Sending to <strong>#{status.channel_name || status.channel_id}</strong>
                  </p>
                </div>
              </div>
              <div className="flex gap-1.5">
                <button onClick={toggleEnabled} className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition">
                  {status.enabled ? 'Pause' : 'Resume'}
                </button>
                <button onClick={sendTest} className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition">
                  Send Test
                </button>
                <button onClick={disconnect} className="text-xs px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400/70 hover:text-red-400 transition">
                  Disconnect
                </button>
              </div>
            </div>
            {testResult && (
              <p className={`text-xs mt-3 ${testResult.startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>{testResult}</p>
            )}
          </Card>

          {/* Channel selector */}
          {channels.length > 0 && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-2">Delivery Channel</h2>
              <select
                className="w-full rounded-lg border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
                value={status.channel_id || ''}
                onChange={e => changeChannel(e.target.value)}
              >
                {channels.map(c => <option key={c.id} value={c.id}>#{c.name}</option>)}
              </select>
            </Card>
          )}

          {/* Event types — grouped and labeled */}
          <Card className="p-5">
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-[var(--tc-text)]">Alert Configuration</h2>
              <p className="text-xs text-[var(--tc-muted)] mt-0.5">
                Select which events trigger Slack notifications. We recommend enabling all compliance alerts.
              </p>
            </div>

            {hasNoSelection && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-4 py-2.5 mb-4">
                <p className="text-xs text-amber-300">
                  <strong>No events selected.</strong> All events will be sent to Slack, which can be noisy.
                  Select specific events below for a better experience.
                </p>
              </div>
            )}

            <EventCheckboxGroup
              events={allEvents}
              checked={currentEvents}
              onChange={updateEvents}
            />
          </Card>

          {/* Preview panel */}
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">Message Preview</h2>
            <p className="text-xs text-[var(--tc-muted)] mb-3">Example of what alerts look like in Slack</p>
            <div className="rounded-lg border border-[var(--tc-border)] bg-[rgba(0,0,0,0.2)] p-4 space-y-2.5">
              {(currentEvents.length > 0
                ? currentEvents.slice(0, 4)
                : ['compliance.coverage_drop', 'compliance.blind_spot', 'questionnaire.generated']
              ).map(evt => {
                const meta = EVENT_META[evt]
                const preview = meta?.preview ?? `${eventLabel(evt)} event triggered`
                return (
                  <div key={evt} className="flex items-start gap-2.5">
                    <div className="w-5 h-5 rounded bg-[#4A154B] flex items-center justify-center shrink-0 mt-0.5">
                      <span className="text-[10px] text-white font-bold">S</span>
                    </div>
                    <div className="min-w-0">
                      <span className="text-[11px] font-semibold text-[var(--tc-text)]">Trust Copilot</span>
                      <span className="text-[10px] text-[var(--tc-muted)] ml-2">12:34 PM</span>
                      <p className="text-xs text-[var(--tc-muted)] mt-0.5">{preview}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>
      ) : (
        /* ── Evidence Ingest tab ── */
        <div className="space-y-6">
          <Card className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--tc-text)]">Approved Ingest Channels</h2>
                <p className="text-xs text-[var(--tc-muted)] mt-0.5">Messages from these channels are ingested as compliance evidence.</p>
              </div>
              <Button onClick={() => { setAddChOpen(true); setError(null) }}>Add channel</Button>
            </div>
            {ingestChannels.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">No channels approved for ingestion yet.</p>
            ) : (
              <div className="space-y-1">
                {ingestChannels.map(ch => (
                  <div key={ch.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="min-w-0">
                      <span className="text-sm text-[var(--tc-text)] font-medium">#{ch.channel_name || ch.channel_id}</span>
                      <span className="text-xs text-[var(--tc-muted)] ml-2">{ch.channel_id}</span>
                      {ch.created_at && (
                        <span className="text-xs text-[var(--tc-muted)] ml-2">· added {new Date(ch.created_at).toLocaleDateString()}</span>
                      )}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        disabled={ingestRunning === ch.id}
                        onClick={() => runIngest(ch.id)}
                        className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-40 transition"
                      >
                        {ingestRunning === ch.id ? 'Running...' : 'Run ingest'}
                      </button>
                      <button
                        onClick={() => removeIngestChannel(ch.id)}
                        className="text-xs px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400/70 hover:text-red-400 transition"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {ingestResult && <p className="text-xs mt-3 text-emerald-400">{ingestResult}</p>}
          </Card>

          {ingestEvidence.length > 0 && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">Ingested Evidence</h2>
              <div className="space-y-1">
                {ingestEvidence.map(ev => (
                  <div key={ev.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="min-w-0">
                      <span className="text-sm text-[var(--tc-text)]">{ev.title}</span>
                      <span className="text-xs text-[var(--tc-muted)] ml-2">
                        #{ev.source_metadata?.channel_name || ev.source_metadata?.channel_id || '—'}
                      </span>
                    </div>
                    <span className="text-xs text-[var(--tc-muted)] shrink-0">
                      {ev.created_at ? new Date(ev.created_at).toLocaleDateString() : '—'}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {ingestSuggestions.length > 0 && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">
                Pending Review ({ingestSuggestions.length})
              </h2>
              <div className="space-y-1">
                {ingestSuggestions.map(s => (
                  <div key={s.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="text-sm text-[var(--tc-text)]">
                      Evidence #{s.evidence_id}
                      {s.confidence != null && (
                        <span className="ml-2 text-xs text-[var(--tc-muted)]">{(s.confidence * 100).toFixed(0)}% relevance</span>
                      )}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button onClick={() => reviewSuggestion(s.id, 'approve')} className="text-xs px-3 py-1.5 rounded-lg border border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/10 transition">
                        Approve
                      </button>
                      <button onClick={() => reviewSuggestion(s.id, 'dismiss')} className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition">
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* ── Add ingest channel modal ── */}
      <Modal isOpen={addChOpen} onClose={() => setAddChOpen(false)} title="Add Ingest Channel">
        <form onSubmit={addIngestChannel} className="space-y-4">
          <Input label="Channel ID" value={addChId} onChange={e => setAddChId(e.target.value)} placeholder="C01ABC23DEF" required />
          <Input label="Channel name (optional)" value={addChName} onChange={e => setAddChName(e.target.value)} placeholder="#evidence" />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={() => setAddChOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Adding...' : 'Add Channel'}</Button>
          </div>
        </form>
      </Modal>

      {/* ── Connect Slack modal ── */}
      <Modal isOpen={connectOpen} onClose={() => setConnectOpen(false)} title="Connect Slack">
        <form onSubmit={connect} className="space-y-4">
          <Input label="Bot token" type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="xoxb-..." required />
          <Input label="Channel ID" value={channelId} onChange={e => setChannelId(e.target.value)} placeholder="C01ABC23DEF" required />
          <Input label="Channel name (optional)" value={channelName} onChange={e => setChannelName(e.target.value)} placeholder="#compliance-alerts" />
          <div>
            <label className="block text-sm font-medium text-[var(--tc-text)] mb-2">
              Events to notify on
            </label>
            <p className="text-xs text-[var(--tc-muted)] mb-3">
              Choose which events trigger Slack messages. We recommend starting with compliance alerts.
            </p>
            <div className="max-h-56 overflow-y-auto pr-1">
              <EventCheckboxGroup
                events={allEvents}
                checked={selectedEvents}
                onChange={setSelectedEvents}
                size="compact"
              />
            </div>
          </div>
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={() => setConnectOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Connecting...' : 'Connect'}</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
