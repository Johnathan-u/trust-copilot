'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  ErrorState,
  LoadingState,
  Modal,
  useDestructiveConfirm,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import type { ApiFailurePresentation } from '@/lib/api-error'
import {
  failureOf,
  isAbortError,
  loadSection,
  readSectionJson,
  type SectionResult,
} from '@/lib/section-load'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'
import { deleteNotificationPolicy } from '@/lib/notification-policy-delete'
import { toggleNotificationPolicy } from '@/lib/notification-policy-toggle'
import {
  RECIPIENT_VALUE_MAX_LENGTH,
  ROLE_RECIPIENT_LABEL,
  USER_RECIPIENT_HELP,
  USER_RECIPIENT_LABEL,
  activeWorkspaceMembers,
  policyCreateErrorMessage,
  readWorkspaceMembers,
  type WorkspaceMemberOption,
} from '@/lib/notification-rule-form'
import {
  DELIVERY_ATTEMPTS_PATH,
  displayDeliveryAttempt,
  parseDeliveryAttempts,
  type DeliveryAttemptsPage,
} from '@/lib/delivery-attempts'
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
  delivery_state?: string | null
  delivered_to_provider?: boolean
  provider_mode?: string | null
  dedupe_key?: string | null
  attempt_count?: number | null
  created_at: string | null
}

type ChannelSwitches = {
  email: boolean
  slack: boolean
  in_app: boolean
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

function deliveryTone(entry: LogEntry): string {
  const state = entry.delivery_state || entry.status
  if (state === 'sent') return 'text-emerald-400'
  if (state === 'failed' || state === 'dead-lettered') return 'text-red-400'
  return 'text-amber-300'
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

function DeliveryAttemptsPanel({
  loading,
  result,
  onRetry,
}: {
  loading: boolean
  result: SectionResult<DeliveryAttemptsPage> | null
  onRetry: () => void
}) {
  let body: React.ReactNode
  if (loading || result === null) {
    body = (
      <LoadingState label="Loading delivery attempts" onRetry={onRetry}>
        <p className="text-sm text-[var(--tc-muted)]">
          Loading delivery attempts
        </p>
      </LoadingState>
    )
  } else if (result.ok === false) {
    body = <ErrorState failure={result.failure} onRetry={onRetry} />
  } else if (result.data.attempts.length === 0) {
    body = (
      <p data-state="empty" className="text-sm text-[var(--tc-muted)]">
        No delivery attempts yet.
      </p>
    )
  } else {
    body = (
      <div className="space-y-1">
        {result.data.attempts.map((attempt) => {
          const row = displayDeliveryAttempt(attempt)
          return (
            <article
              key={attempt.id}
              className="min-w-0 rounded-lg border border-[var(--tc-border)] px-4 py-2.5"
            >
              <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-sm text-[var(--tc-text)]">
                <span className="text-xs uppercase text-[var(--tc-muted)]">
                  {row.channel}
                </span>
                <span className="min-w-0 break-words">{row.template}</span>
                <span className="min-w-0 break-words text-[var(--tc-muted)]">
                  {row.event}
                </span>
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--tc-muted)]">
                <span className="min-w-0 break-words">
                  Destination {row.destination}
                </span>
                <span className="inline-flex flex-wrap gap-x-1">
                  <span>State</span>
                  <span>{row.state}</span>
                  {row.claimed ? <span>claimed</span> : null}
                </span>
                <span>Attempts {row.attempts}</span>
                <span>{row.read}</span>
              </div>
            </article>
          )
        })}
      </div>
    )
  }

  return (
    <Card className="p-5">
      <section aria-labelledby="delivery-attempts-heading">
        <h2
          id="delivery-attempts-heading"
          className="text-sm font-semibold text-[var(--tc-text)]"
        >
          Delivery attempts
        </h2>
        <p className="text-xs text-[var(--tc-muted)] mt-0.5 mb-4">
          Recent tries for this workspace. The destination is the redacted value
          returned by the API.
        </p>
        {body}
      </section>
    </Card>
  )
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
  const [loadFailure, setLoadFailure] = useState<ApiFailurePresentation | null>(
    null
  )
  const [addOpen, setAddOpen] = useState(false)
  const [addEvt, setAddEvt] = useState('')
  const [addRecipType, setAddRecipType] = useState('admins')
  const [addRecipVal, setAddRecipVal] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [members, setMembers] = useState<WorkspaceMemberOption[]>([])
  const [membersError, setMembersError] = useState<string | null>(null)
  const [membersLoading, setMembersLoading] = useState(false)
  const [policyError, setPolicyError] = useState<string | null>(null)
  const { confirm, dialog: confirmDialog } = useDestructiveConfirm()
  const [stubProviders, setStubProviders] = useState<string[]>([])
  const [channels, setChannels] = useState<ChannelSwitches>({
    email: true,
    slack: true,
    in_app: false,
  })
  const [prefError, setPrefError] = useState<string | null>(null)
  const [prefSaved, setPrefSaved] = useState<string | null>(null)
  const savingPref = useRef(false)
  const [attemptResult, setAttemptResult] =
    useState<SectionResult<DeliveryAttemptsPage> | null>(null)
  const [attemptsLoading, setAttemptsLoading] = useState(true)

  const loadPreferences = useCallback(() => {
    fetch('/api/notifications/channel-preferences', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const effective = data?.effective
        if (!effective) return
        setChannels({
          email: Boolean(effective.email),
          slack: Boolean(effective.slack),
          in_app: Boolean(effective.in_app),
        })
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadPreferences()
  }, [loadPreferences])

  const loadMembers = useCallback(() => {
    setMembersLoading(true)
    setMembersError(null)
    fetch('/api/members', { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error('unavailable')
        return response.json()
      })
      .then((data) => {
        setMembers(readWorkspaceMembers(data))
      })
      .catch(() => {
        setMembers([])
        setMembersError('Workspace members could not be loaded.')
      })
      .finally(() => setMembersLoading(false))
  }, [])

  const setChannel = async (
    channel: keyof ChannelSwitches,
    enabled: boolean
  ) => {
    if (savingPref.current) return
    savingPref.current = true
    setPrefError(null)
    setPrefSaved(null)
    try {
      const r = await fetch('/api/notifications/channel-preferences', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel, enabled }),
      })
      if (!r.ok) {
        setPrefError('Could not save that channel preference.')
        return
      }
      setChannels((prev) => ({ ...prev, [channel]: enabled }))
      setPrefSaved('Channel preference saved.')
    } catch {
      setPrefError('Could not save that channel preference.')
    } finally {
      savingPref.current = false
    }
  }

  const requestAttempts = useCallback((signal?: AbortSignal) => {
    return loadSection(
      fetch(`${DELIVERY_ATTEMPTS_PATH}?page=1&page_size=50`, {
        credentials: 'include',
        signal,
      }),
      parseDeliveryAttempts
    )
  }, [])

  useEffect(() => {
    if (!canAdmin) return
    const controller = new AbortController()
    let active = true
    requestAttempts(controller.signal)
      .then((result) => {
        if (!active) return
        setAttemptResult(result)
        setAttemptsLoading(false)
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return
        setAttemptResult({ ok: false, failure: failureOf(error) })
        setAttemptsLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [canAdmin, requestAttempts])

  useEffect(() => {
    if (!canAdmin) return
    Promise.all([
      fetch('/api/slack/status', { credentials: 'include' }).then((r) =>
        r.ok ? r.json() : null
      ),
      fetch('/api/gmail/status', { credentials: 'include' }).then((r) =>
        r.ok ? r.json() : null
      ),
    ])
      .then(([slack, gmail]) => {
        const stubs = [
          slack?.provider_mode === 'dev-stub' ? 'Slack' : null,
          gmail?.provider_mode === 'dev-stub' ? 'Gmail' : null,
        ].filter((name): name is string => Boolean(name))
        setStubProviders(stubs)
      })
      .catch(() => {})
  }, [canAdmin])

  const queryAlerts = useCallback(() => {
    Promise.all([
      fetch('/api/compliance-alerts/active', { credentials: 'include' }).then(
        (r) => readSectionJson(r)
      ),
      fetch('/api/notifications/event-types', { credentials: 'include' }).then(
        (r) => readSectionJson(r)
      ),
      fetch('/api/notifications/policies', { credentials: 'include' }).then(
        (r) => readSectionJson(r)
      ),
      fetch(`/api/notifications/log?page=${logPage}&page_size=25`, {
        credentials: 'include',
      }).then((r) => readSectionJson(r)),
    ])
      .then(([alertsData, evtData, polData, logData]) => {
        const alerts = alertsData as { alerts?: ActiveAlert[] }
        const events = evtData as { event_types?: string[] }
        const policies = polData as { policies?: Policy[] }
        const log = logData as { entries?: LogEntry[]; total?: number }
        if (
          !Array.isArray(alerts.alerts) ||
          !Array.isArray(events.event_types) ||
          !Array.isArray(policies.policies) ||
          !Array.isArray(log.entries)
        ) {
          throw new Error('malformed')
        }
        setActiveAlerts(alerts.alerts)
        setEventTypes(events.event_types)
        setPolicies(policies.policies)
        setLogEntries(log.entries)
        setLogTotal(log.total ?? 0)
        setLoadFailure(null)
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        setActiveAlerts([])
        setEventTypes([])
        setPolicies([])
        setLogEntries([])
        setLogTotal(0)
        setLoadFailure(failureOf(error))
      })
      .finally(() => setLoading(false))
  }, [logPage])

  const load = useCallback(() => {
    setLoading(true)
    setLoadFailure(null)
    queryAlerts()
  }, [queryAlerts])

  const alertsKey = useKeyedGeneration(`${canAdmin ? '1' : '0'}|${logPage}`)
  if (alertsKey.changed) {
    setLoading(canAdmin)
    if (canAdmin) setLoadFailure(null)
  }

  useEffect(() => {
    if (!canAdmin) return
    queryAlerts()
  }, [canAdmin, queryAlerts])

  useEffect(() => {
    if (!canAdmin) return
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [canAdmin, load])

  const togglePolicy = (p: Policy) =>
    toggleNotificationPolicy(p, { reload: load, setError: setPolicyError })

  const deletePolicy = (p: Policy) => {
    const label = getNotificationTitle(p.event_type)
    confirm({
      title: 'Remove alert rule?',
      description: `Remove alert rule "${label}"?`,
      confirmLabel: 'Remove',
      onConfirm: () => deleteNotificationPolicy(p.id, load),
    })
  }

  const addPolicy = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!addEvt) {
      setFormError('Select an event')
      return
    }
    if (addRecipType === 'user' && !/^[1-9]\d*$/.test(addRecipVal)) {
      setFormError('Select a workspace member')
      return
    }
    if (addRecipType === 'role' && !addRecipVal.trim()) {
      setFormError('Enter a role name')
      return
    }
    setSubmitting(true)
    setFormError(null)
    try {
      const r = await fetch('/api/notifications/policies', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: addEvt,
          recipient_type: addRecipType,
          recipient_value: addRecipVal || undefined,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        const detail =
          d && typeof d === 'object' && 'detail' in d
            ? (d as { detail?: unknown }).detail
            : undefined
        setFormError(policyCreateErrorMessage(detail))
        return
      }
      setAddOpen(false)
      setAddEvt('')
      setAddRecipType('admins')
      setAddRecipVal('')
      load()
    } finally {
      setSubmitting(false)
    }
  }

  const channelCard = (
    <Card className="p-5">
      <h2 className="text-sm font-semibold text-[var(--tc-text)]">
        Your channels
      </h2>
      <p className="text-xs text-[var(--tc-muted)] mt-0.5 mb-3">
        These switches are for your user. Turning a channel off stops that
        channel for you. Email and Slack start on. In-app starts off until you
        enable it. Workspace alert rules are separate.
      </p>
      <div className="flex flex-wrap gap-4">
        {(
          [
            ['email', 'Email'],
            ['slack', 'Slack'],
            ['in_app', 'In-app'],
          ] as const
        ).map(([key, label]) => (
          <label
            key={key}
            className="flex items-center gap-2 text-sm text-[var(--tc-text)]"
          >
            <input
              type="checkbox"
              checked={channels[key]}
              onChange={(e) => setChannel(key, e.target.checked)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                event.preventDefault()
                void setChannel(key, !channels[key])
              }}
            />
            {label}
          </label>
        ))}
      </div>
      {prefSaved && (
        <p role="status" className="mt-2 text-sm text-[var(--tc-text)]">
          {prefSaved}
        </p>
      )}
      {prefError && (
        <p role="alert" className="mt-2 text-sm text-[var(--tc-danger)]">
          {prefError}
        </p>
      )}
    </Card>
  )

  if (!canAdmin) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">
            Alerts / Notifications
          </h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">
            Admin access is required to manage workspace alert rules. You can
            still choose your own channels.
          </p>
        </div>
        {channelCard}
      </div>
    )
  }

  const configuredEvents = new Set(policies.map((p) => p.event_type))
  const availableEvents = eventTypes.filter((e) => !configuredEvents.has(e))
  const logPages = Math.max(1, Math.ceil(logTotal / 25))

  const groupedAvailable: Record<NotificationCategory, string[]> = {
    compliance: availableEvents.filter(
      (e) => getNotificationCategory(e) === 'compliance'
    ),
    system: availableEvents.filter(
      (e) => getNotificationCategory(e) === 'system'
    ),
    team: availableEvents.filter((e) => getNotificationCategory(e) === 'team'),
  }

  const groupedPolicies: Record<NotificationCategory, Policy[]> = {
    compliance: policies.filter(
      (p) => getNotificationCategory(p.event_type) === 'compliance'
    ),
    system: policies.filter(
      (p) => getNotificationCategory(p.event_type) === 'system'
    ),
    team: policies.filter(
      (p) => getNotificationCategory(p.event_type) === 'team'
    ),
  }

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">
          Alerts / Notifications
        </h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">
          Stay informed about important changes in your compliance coverage,
          system events, and team activity.
        </p>
      </div>

      {stubProviders.length > 0 && (
        <div
          role="status"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100"
        >
          <strong className="font-semibold">Development stub.</strong>{' '}
          {stubProviders.join(' and ')}{' '}
          {stubProviders.length === 1 ? 'is' : 'are'} not called. A log row from
          the stub is not delivery to that provider. Production preflight
          rejects this mode.
        </div>
      )}

      {channelCard}

      <DeliveryAttemptsPanel
        loading={attemptsLoading}
        result={attemptResult}
        onRetry={() => {
          setAttemptsLoading(true)
          void requestAttempts().then((result) => {
            setAttemptResult(result)
            setAttemptsLoading(false)
          })
        }}
      />

      {loadFailure ? (
        <ErrorState failure={loadFailure} onRetry={() => void load()} />
      ) : loading ? (
        <LoadingState label="Loading alerts" onRetry={() => void load()}>
          <Card className="p-6">
            <p className="text-tc-label text-tc-muted">Loading alerts</p>
          </Card>
        </LoadingState>
      ) : (
        <>
          {/* ── SECTION 1 — Active Alerts / Important Now ── */}
          <div>
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3">
              Important Now
            </h2>
            {activeAlerts.length === 0 ? (
              <Card className="p-4">
                <div className="flex items-center gap-3">
                  <span className="text-lg">✅</span>
                  <p className="text-sm text-[var(--tc-muted)]">
                    No active alerts. Your compliance coverage looks healthy.
                  </p>
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
                      <span
                        className={`mt-1 inline-block h-2 w-2 rounded-full shrink-0 ${severityDot(alert.severity)}`}
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-sm font-semibold ${severityColor(alert.severity)}`}
                          >
                            {alert.title}
                          </span>
                          <span
                            className={`text-[10px] uppercase font-medium px-1.5 py-0.5 rounded ${alert.severity === 'high' ? 'bg-red-500/20 text-red-300' : 'bg-amber-500/20 text-amber-300'}`}
                          >
                            {alert.severity}
                          </span>
                        </div>
                        <p className="text-xs text-[var(--tc-muted)] mt-0.5">
                          {alert.description}
                        </p>
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
                <h2 className="text-sm font-semibold text-[var(--tc-text)]">
                  Alert Rules
                </h2>
                <p className="text-xs text-[var(--tc-muted)] mt-0.5">
                  Configure which events trigger email notifications. A specific
                  user is an active workspace member, stored by that member's
                  user id.
                </p>
              </div>
              <Button
                disabled={availableEvents.length === 0}
                onClick={() => {
                  setAddOpen(true)
                  setFormError(null)
                  if (addRecipType === 'user') loadMembers()
                  const first =
                    groupedAvailable.compliance[0] ||
                    groupedAvailable.system[0] ||
                    groupedAvailable.team[0] ||
                    ''
                  setAddEvt(first)
                }}
              >
                Add rule
              </Button>
            </div>

            {policyError && (
              <p role="alert" className="mb-4 text-sm text-[var(--tc-danger)]">
                {policyError}
              </p>
            )}

            {policies.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">
                No alert rules configured yet. Add a rule to start receiving
                notifications.
              </p>
            ) : (
              <div className="space-y-5">
                {(['compliance', 'system', 'team'] as const).map((cat) => {
                  const catPolicies = groupedPolicies[cat]
                  if (catPolicies.length === 0) return null
                  const meta = CATEGORY_META[cat]
                  return (
                    <div key={cat}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm">{meta.icon}</span>
                        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--tc-muted)]">
                          {meta.label}
                        </span>
                      </div>
                      <div className="space-y-1">
                        {catPolicies.map((p) => (
                          <div
                            key={p.id}
                            className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition"
                          >
                            <div className="flex items-center gap-3 min-w-0">
                              <span
                                className={`inline-block h-2 w-2 rounded-full shrink-0 ${p.enabled ? 'bg-emerald-400' : 'bg-slate-500'}`}
                              />
                              <div className="min-w-0">
                                <span className="text-sm text-[var(--tc-text)]">
                                  {getNotificationTitle(p.event_type)}
                                </span>
                                <span className="text-xs text-[var(--tc-muted)] ml-2">
                                  →{' '}
                                  {p.recipient_type === 'admins'
                                    ? 'Admins'
                                    : p.recipient_type === 'all'
                                      ? 'All members'
                                      : `${p.recipient_type}: ${p.recipient_value || ''}`}
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
            <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-1">
              Recent Activity
            </h2>
            <p className="text-xs text-[var(--tc-muted)] mb-4">
              Notification delivery history
            </p>
            {logEntries.length === 0 ? (
              <p className="text-sm text-[var(--tc-muted)]">
                No notification history yet.
              </p>
            ) : (
              <>
                <div className="space-y-1">
                  {logEntries.map((entry) => {
                    const meta = getNotificationMeta(entry.event_type)
                    return (
                      <div
                        key={entry.id}
                        className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--tc-border)] px-4 py-2.5 hover:bg-white/[0.02] transition"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <span
                            className={`inline-block h-2 w-2 rounded-full shrink-0 ${severityDot(meta.severity)}`}
                          />
                          <div className="min-w-0">
                            <span className="text-sm text-[var(--tc-text)]">
                              {meta.title}
                            </span>
                            <span className="text-xs text-[var(--tc-muted)] ml-2">
                              → {entry.recipient_email}
                            </span>
                          </div>
                        </div>
                        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                          <span className="text-[10px] uppercase text-[var(--tc-muted)]">
                            {entry.channel || 'email'}
                          </span>
                          <span
                            className={`text-[10px] uppercase font-medium ${deliveryTone(entry)}`}
                          >
                            {(
                              entry.delivery_state ||
                              entry.status ||
                              ''
                            ).replaceAll('-', ' ')}
                          </span>
                          {entry.provider_mode === 'dev-stub' && (
                            <span className="text-[10px] uppercase font-medium text-amber-300">
                              Not delivered to the provider
                            </span>
                          )}
                          <span className="text-xs text-[var(--tc-muted)]">
                            {timeAgo(entry.created_at)}
                          </span>
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
                    <span className="text-xs text-[var(--tc-muted)]">
                      Page {logPage} of {logPages}
                    </span>
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

      {confirmDialog}
      {/* ── SECTION 3 — Add Alert Rule Modal ── */}
      <Modal
        isOpen={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add Alert Rule"
      >
        <form onSubmit={addPolicy} className="space-y-4">
          <div>
            <label
              htmlFor="rule-event"
              className="block text-sm font-medium text-[var(--tc-text)] mb-2"
            >
              Event
            </label>
            <select
              id="rule-event"
              className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
              value={addEvt}
              onChange={(e) => setAddEvt(e.target.value)}
            >
              {(['compliance', 'system', 'team'] as const).map((cat) => {
                const items = groupedAvailable[cat]
                if (items.length === 0) return null
                return (
                  <optgroup key={cat} label={CATEGORY_META[cat].label}>
                    {items.map((et) => (
                      <option key={et} value={et}>
                        {getNotificationTitle(et)}
                      </option>
                    ))}
                  </optgroup>
                )
              })}
            </select>
            {addEvt && (
              <p className="mt-1.5 text-xs text-[var(--tc-muted)]">
                {getNotificationMeta(addEvt).description}
              </p>
            )}
          </div>
          <div>
            <label
              htmlFor="rule-recipients"
              className="block text-sm font-medium text-[var(--tc-text)] mb-2"
            >
              Recipients
            </label>
            <select
              id="rule-recipients"
              className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
              value={addRecipType}
              onChange={(e) => {
                const nextType = e.target.value
                setAddRecipType(nextType)
                setAddRecipVal('')
                setFormError(null)
                if (nextType === 'user') loadMembers()
              }}
            >
              {RECIPIENT_TYPES.map((rt) => (
                <option key={rt.value} value={rt.value}>
                  {rt.label}
                </option>
              ))}
            </select>
          </div>
          {addRecipType === 'role' && (
            <div>
              <label
                htmlFor="rule-role"
                className="block text-sm font-medium text-[var(--tc-text)] mb-2"
              >
                {ROLE_RECIPIENT_LABEL}
              </label>
              <input
                id="rule-role"
                className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
                value={addRecipVal}
                maxLength={RECIPIENT_VALUE_MAX_LENGTH}
                onChange={(e) => setAddRecipVal(e.target.value)}
                placeholder="e.g. editor"
              />
            </div>
          )}
          {addRecipType === 'user' && (
            <div>
              <label
                htmlFor="rule-member"
                className="block text-sm font-medium text-[var(--tc-text)] mb-2"
              >
                {USER_RECIPIENT_LABEL}
              </label>
              <select
                id="rule-member"
                className="w-full rounded border border-[var(--tc-border)] bg-[var(--tc-panel)] px-3 py-2 text-sm text-[var(--tc-text)]"
                value={addRecipVal}
                aria-describedby="rule-member-help"
                disabled={membersLoading || Boolean(membersError)}
                onChange={(e) => setAddRecipVal(e.target.value)}
              >
                <option value="">
                  {membersLoading ? 'Loading members' : 'Select a member'}
                </option>
                {activeWorkspaceMembers(members).map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.display_name || member.email}
                  </option>
                ))}
              </select>
              <p
                id="rule-member-help"
                className="mt-1.5 text-xs text-[var(--tc-muted)]"
              >
                {USER_RECIPIENT_HELP}
              </p>
              {membersError && (
                <p
                  role="alert"
                  className="mt-1.5 text-sm text-[var(--tc-danger)]"
                >
                  {membersError}
                </p>
              )}
            </div>
          )}
          {formError && (
            <p role="alert" className="text-sm text-[var(--tc-danger)]">
              {formError}
            </p>
          )}
          <div className="flex gap-2 justify-end pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setAddOpen(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Adding...' : 'Add Rule'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
