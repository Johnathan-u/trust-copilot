'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Input, Modal } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ──────────────────── Types ──────────────────── */

type GmailStatus = { connected: boolean; enabled?: boolean; email_address?: string; updated_at?: string }
type Label = { id: string; name: string }
type IngestLabel = { id: number; label_id: string; label_name: string | null; enabled: boolean; created_at: string | null }
type Evidence = { id: number; title: string; source_metadata: Record<string, string> | null; created_at: string | null }
type Suggestion = { id: number; evidence_id: number; control_id: number; confidence: number | null; status: string }

/* ──────────────────── Helpers ──────────────────── */

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

const VALUE_POINTS = [
  { icon: '📧', title: 'Capture email evidence', description: 'Ingest compliance-related emails and attachments from labeled folders' },
  { icon: '📎', title: 'Auto-extract attachments', description: 'PDFs, DOCX, XLSX, and other documents are automatically indexed as evidence' },
  { icon: '🔍', title: 'Searchable & linked', description: 'Ingested evidence becomes searchable and can support questionnaire answering' },
  { icon: '🏷️', title: 'Label-based filtering', description: 'Choose which Gmail labels to monitor — only ingest what matters' },
]

/* ──────────────────── Component ──────────────────── */

export default function GmailPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const [status, setStatus] = useState<GmailStatus>({ connected: false })
  const [labels, setLabels] = useState<Label[]>([])
  const [ingestLabels, setIngestLabels] = useState<IngestLabel[]>([])
  const [evidence, setEvidence] = useState<Evidence[]>([])
  const [evidenceTotal, setEvidenceTotal] = useState(0)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [connectOpen, setConnectOpen] = useState(false)
  const [token, setToken] = useState('')
  const [refreshToken, setRefreshToken] = useState('')
  const [addLabelOpen, setAddLabelOpen] = useState(false)
  const [addLabelId, setAddLabelId] = useState('')
  const [addLabelName, setAddLabelName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ingestRunning, setIngestRunning] = useState<number | null>(null)
  const [ingestResult, setIngestResult] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    fetch('/api/gmail/status', { credentials: 'include' })
      .then(r => r.ok ? r.json() : { connected: false })
      .then(d => {
        setStatus(d)
        if (d.connected) {
          Promise.all([
            fetch('/api/gmail/labels', { credentials: 'include' }).then(r => r.ok ? r.json() : { labels: [] }),
            fetch('/api/gmail/ingest/labels', { credentials: 'include' }).then(r => r.ok ? r.json() : { labels: [] }),
            fetch('/api/gmail/ingest/evidence?page_size=20', { credentials: 'include' }).then(r => r.ok ? r.json() : { evidence: [], total: 0 }),
            fetch('/api/gmail/ingest/suggestions?status=pending', { credentials: 'include' }).then(r => r.ok ? r.json() : { suggestions: [] }),
          ]).then(([d1, d2, d3, d4]) => {
            setLabels(d1.labels ?? [])
            setIngestLabels(d2.labels ?? [])
            setEvidence(d3.evidence ?? [])
            setEvidenceTotal(d3.total ?? 0)
            setSuggestions(d4.suggestions ?? [])
          }).catch(() => {})
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { if (canAdmin) load(); else setLoading(false) }, [canAdmin, load])

  const connect = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token.trim()) { setError('Access token required'); return }
    setSubmitting(true); setError(null)
    try {
      const r = await fetch('/api/gmail/connect', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ access_token: token, refresh_token: refreshToken || undefined }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(d.detail || 'Failed'); return }
      setConnectOpen(false); setToken(''); setRefreshToken('')
      load()
    } finally { setSubmitting(false) }
  }

  const disconnect = async () => {
    if (!confirm('Disconnect Gmail? Evidence ingestion will stop.')) return
    await fetch('/api/gmail/disconnect', { method: 'DELETE', credentials: 'include' })
    load()
  }

  const addLabel = async (labelId: string, labelName?: string) => {
    setSubmitting(true); setError(null)
    try {
      const r = await fetch('/api/gmail/ingest/labels', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label_id: labelId, label_name: labelName || undefined }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setError(d.detail || 'Failed'); return }
      setAddLabelOpen(false); setAddLabelId(''); setAddLabelName('')
      load()
    } finally { setSubmitting(false) }
  }

  const addLabelSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!addLabelId.trim()) { setError('Label ID required'); return }
    addLabel(addLabelId.trim(), addLabelName.trim())
  }

  const removeLabel = async (id: number) => {
    if (!confirm('Remove this label from ingestion?')) return
    await fetch(`/api/gmail/ingest/labels/${id}`, { method: 'DELETE', credentials: 'include' })
    load()
  }

  const runIngest = async (recId: number) => {
    setIngestRunning(recId); setIngestResult(null)
    try {
      const r = await fetch(`/api/gmail/ingest/run/${recId}?limit=20`, { method: 'POST', credentials: 'include' })
      const d = await r.json().catch(() => ({}))
      setIngestResult(r.ok
        ? `Ingested ${d.ingested ?? 0} emails, ${d.attachments ?? 0} attachments, skipped ${d.skipped ?? 0}`
        : `Error: ${d.detail || 'failed'}`)
      load()
    } finally { setIngestRunning(null) }
  }

  const reviewSuggestion = async (id: number, action: 'approve' | 'dismiss') => {
    await fetch(`/api/gmail/ingest/suggestions/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    load()
  }

  if (!canAdmin) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Gmail Integration</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">Admin access required to manage Gmail integration.</p>
        </div>
      </div>
    )
  }

  const lastEvidence = evidence.length > 0 ? evidence[0] : null
  const approvedLabelIds = new Set(ingestLabels.map(l => l.label_id))
  const availableLabels = labels.filter(l => !approvedLabelIds.has(l.id))

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Gmail Integration</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">
            Ingest compliance evidence directly from email.
          </p>
        </div>
        {!loading && !status.connected && (
          <Button onClick={() => { setConnectOpen(true); setError(null) }}>Connect Gmail</Button>
        )}
      </div>

      {loading ? (
        <Card className="p-6"><p className="text-[var(--tc-muted)]">Loading...</p></Card>
      ) : !status.connected ? (
        /* ════════════════════ DISCONNECTED STATE ════════════════════ */
        <>
          {/* Section 1 — Value proposition */}
          <Card className="p-6">
            <div className="flex items-center gap-3">
              <span className="text-3xl">📧</span>
              <div>
                <h2 className="text-base font-semibold text-[var(--tc-text)]">Connect Gmail to capture evidence from email</h2>
                <p className="text-sm text-[var(--tc-muted)] mt-0.5">
                  Automatically ingest vendor responses, audit documentation, and compliance-related attachments
                  from your inbox into searchable evidence.
                </p>
              </div>
            </div>
          </Card>

          {/* Section 2 — How it works */}
          <div>
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">How it works</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {VALUE_POINTS.map((vp, i) => (
                <Card key={i} className="p-4 flex gap-3">
                  <span className="text-lg shrink-0">{vp.icon}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-[var(--tc-text)]">{vp.title}</p>
                    <p className="text-xs text-[var(--tc-muted)] mt-0.5">{vp.description}</p>
                  </div>
                </Card>
              ))}
            </div>
          </div>

          {/* Section 3 — What happens after */}
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">After connecting</h2>
            <div className="space-y-2">
              {[
                'Choose which Gmail labels to monitor for compliance content',
                'Run ingestion to scan emails and extract attachments',
                'Documents are automatically indexed and become searchable evidence',
                'Ingested evidence can be used to answer questionnaire questions',
              ].map((step, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <span className="text-xs font-bold text-[var(--tc-primary)] mt-0.5 w-5 text-center">{i + 1}</span>
                  <p className="text-sm text-[var(--tc-muted)]">{step}</p>
                </div>
              ))}
            </div>
          </Card>
        </>
      ) : (
        /* ════════════════════ CONNECTED STATE ════════════════════ */
        <>
          {/* Connection status card */}
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400" />
                <div>
                  <h2 className="text-sm font-semibold text-[var(--tc-text)]">Connected</h2>
                  <p className="text-xs text-[var(--tc-muted)]">
                    {status.email_address
                      ? <>{status.email_address}</>
                      : 'Gmail account connected'}
                  </p>
                </div>
              </div>
              <button
                onClick={disconnect}
                className="text-xs px-3 py-1.5 rounded-lg border border-red-500/20 text-red-400/70 hover:text-red-400 transition"
              >
                Disconnect
              </button>
            </div>

            {/* Stats row */}
            <div className="flex flex-wrap gap-6 mt-4 pt-3 border-t border-[var(--tc-border)]">
              <div>
                <p className="text-xs text-[var(--tc-muted)]">Labels monitored</p>
                <p className="text-lg font-bold text-[var(--tc-text)]">{ingestLabels.length}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--tc-muted)]">Evidence ingested</p>
                <p className="text-lg font-bold text-[var(--tc-text)]">{evidenceTotal}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--tc-muted)]">Last ingestion</p>
                <p className="text-lg font-bold text-[var(--tc-text)]">{lastEvidence ? timeAgo(lastEvidence.created_at) : 'Never'}</p>
              </div>
              {suggestions.length > 0 && (
                <div>
                  <p className="text-xs text-[var(--tc-muted)]">Pending review</p>
                  <p className="text-lg font-bold text-amber-400">{suggestions.length}</p>
                </div>
              )}
            </div>
          </Card>

          {/* Label management */}
          <Card className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--tc-text)]">Monitored Labels</h2>
                <p className="text-xs text-[var(--tc-muted)] mt-0.5">Emails under these labels will be scanned for compliance evidence</p>
              </div>
              <Button onClick={() => { setAddLabelOpen(true); setError(null); setAddLabelId(''); setAddLabelName('') }}>
                Add label
              </Button>
            </div>

            {ingestLabels.length === 0 ? (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3">
                <p className="text-xs text-amber-300">
                  <strong>No labels configured.</strong> Add a Gmail label to start ingesting evidence from email.
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                {ingestLabels.map(l => (
                  <div key={l.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-sm">🏷️</span>
                      <div className="min-w-0">
                        <span className="text-sm text-[var(--tc-text)] font-medium">{l.label_name || l.label_id}</span>
                        {l.created_at && (
                          <span className="text-xs text-[var(--tc-muted)] ml-2">· added {new Date(l.created_at).toLocaleDateString()}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        disabled={ingestRunning === l.id}
                        onClick={() => runIngest(l.id)}
                        className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] disabled:opacity-40 transition"
                      >
                        {ingestRunning === l.id ? 'Running...' : 'Run ingest'}
                      </button>
                      <button
                        onClick={() => removeLabel(l.id)}
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

            {/* Quick-add from available labels */}
            {availableLabels.length > 0 && (
              <div className="mt-4 pt-3 border-t border-[var(--tc-border)]">
                <p className="text-xs text-[var(--tc-muted)] mb-2">Available Gmail labels</p>
                <div className="flex flex-wrap gap-1.5">
                  {availableLabels.slice(0, 20).map(l => (
                    <button
                      key={l.id}
                      onClick={() => addLabel(l.id, l.name)}
                      className="rounded-lg border border-[var(--tc-border)] px-2.5 py-1 text-xs text-[var(--tc-muted)] hover:text-[var(--tc-text)] hover:border-[rgba(91,124,255,0.3)] transition"
                      title={`Add "${l.name}" to monitored labels`}
                    >
                      + {l.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </Card>

          {/* Recent ingestion activity */}
          <Card className="p-5">
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">Recent Evidence</h2>
            <p className="text-xs text-[var(--tc-muted)] mb-3">Documents and emails ingested from Gmail</p>

            {evidence.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">
                No evidence ingested yet. Add a label above and click &quot;Run ingest&quot; to start.
              </p>
            ) : (
              <div className="space-y-1">
                {evidence.map(ev => (
                  <div key={ev.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-sm shrink-0">
                        {ev.title?.match(/\.(pdf|docx?|xlsx?)$/i) ? '📎' : '📧'}
                      </span>
                      <div className="min-w-0">
                        <span className="text-sm text-[var(--tc-text)] truncate block">{ev.title}</span>
                        <span className="text-xs text-[var(--tc-muted)]">
                          {ev.source_metadata?.sender && `from ${ev.source_metadata.sender}`}
                          {ev.source_metadata?.subject && ev.source_metadata.sender && ' · '}
                          {ev.source_metadata?.subject && ev.source_metadata.subject}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-[var(--tc-muted)] shrink-0 ml-3">{timeAgo(ev.created_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Pending suggestions */}
          {suggestions.length > 0 && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">
                Pending Review ({suggestions.length})
              </h2>
              <p className="text-xs text-[var(--tc-muted)] mb-3">Review ingested evidence before it becomes searchable</p>
              <div className="space-y-1">
                {suggestions.map(s => (
                  <div key={s.id} className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition">
                    <div className="text-sm text-[var(--tc-text)]">
                      Evidence #{s.evidence_id}
                      {s.confidence != null && (
                        <span className="ml-2 text-xs text-[var(--tc-muted)]">{(s.confidence * 100).toFixed(0)}% relevance</span>
                      )}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      <button
                        onClick={() => reviewSuggestion(s.id, 'approve')}
                        className="text-xs px-3 py-1.5 rounded-lg border border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/10 transition"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => reviewSuggestion(s.id, 'dismiss')}
                        className="text-xs px-3 py-1.5 rounded-lg border border-[var(--tc-border)] text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {/* ── Connect Gmail modal ── */}
      <Modal isOpen={connectOpen} onClose={() => setConnectOpen(false)} title="Connect Gmail">
        <form onSubmit={connect} className="space-y-4">
          <p className="text-xs text-[var(--tc-muted)]">
            Provide a Google OAuth access token to connect your Gmail account for evidence ingestion.
          </p>
          <Input label="OAuth Access Token" type="password" value={token} onChange={e => setToken(e.target.value)} placeholder="ya29.a0..." required />
          <Input label="Refresh Token (optional)" type="password" value={refreshToken} onChange={e => setRefreshToken(e.target.value)} placeholder="1//0..." />
          <p className="text-[10px] text-[var(--tc-muted)]">
            A refresh token keeps the connection alive long-term. Without one, you may need to reconnect periodically.
          </p>
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={() => setConnectOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Connecting...' : 'Connect'}</Button>
          </div>
        </form>
      </Modal>

      {/* ── Add label modal ── */}
      <Modal isOpen={addLabelOpen} onClose={() => setAddLabelOpen(false)} title="Add Gmail Label">
        <form onSubmit={addLabelSubmit} className="space-y-4">
          <p className="text-xs text-[var(--tc-muted)]">
            Add a Gmail label to monitor. Emails under this label will be scanned during ingestion.
          </p>
          <Input label="Label ID" value={addLabelId} onChange={e => setAddLabelId(e.target.value)} placeholder="Label_Compliance" required />
          <Input label="Label name (optional)" value={addLabelName} onChange={e => setAddLabelName(e.target.value)} placeholder="Compliance" />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={() => setAddLabelOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={submitting}>{submitting ? 'Adding...' : 'Add Label'}</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
