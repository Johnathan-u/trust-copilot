'use client'

import { useEffect, useState, useCallback } from 'react'
import { Button, Card, Input } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

/* ── Types ── */

type Session = {
  id: number
  session_id: string | null
  current: boolean
  user_agent: string | null
  ip_address: string | null
  created_at: string | null
}

type MfaStatus = { enabled: boolean }

type SecurityEvent = {
  id: number
  occurred_at: string
  action: string
  email: string | null
  user_id: number | null
  details: string | null
}

/* ── User-Agent Parser ── */

function parseUA(ua: string | null): { browser: string; os: string; device: string } {
  if (!ua) return { browser: 'Unknown', os: 'Unknown', device: 'Unknown device' }

  let browser = 'Unknown browser'
  let os = 'Unknown OS'

  if (/Edg\//i.test(ua)) browser = 'Microsoft Edge'
  else if (/OPR\//i.test(ua) || /Opera/i.test(ua)) browser = 'Opera'
  else if (/Chrome\//i.test(ua) && !/Chromium/i.test(ua)) browser = 'Chrome'
  else if (/Firefox\//i.test(ua)) browser = 'Firefox'
  else if (/Safari\//i.test(ua) && !/Chrome/i.test(ua)) browser = 'Safari'
  else if (/MSIE|Trident/i.test(ua)) browser = 'Internet Explorer'

  if (/Windows/i.test(ua)) os = 'Windows'
  else if (/Macintosh|Mac OS/i.test(ua)) os = 'macOS'
  else if (/Linux/i.test(ua) && !/Android/i.test(ua)) os = 'Linux'
  else if (/Android/i.test(ua)) os = 'Android'
  else if (/iPhone|iPad|iPod/i.test(ua)) os = 'iOS'
  else if (/CrOS/i.test(ua)) os = 'ChromeOS'

  if (/python-requests|httpx|curl|wget|postman/i.test(ua)) {
    browser = 'API Client'
    os = 'Server'
  }

  const device = `${browser} on ${os}`
  return { browser, os, device }
}

/* ── Security Event Labels ── */

const EVENT_LABELS: Record<string, string> = {
  'auth.login': 'Signed in',
  'auth.login_failed': 'Failed sign-in attempt',
  'auth.logout': 'Signed out',
  'auth.password_changed': 'Password changed',
  'auth.password_reset': 'Password reset',
  'auth.mfa_enabled': 'MFA enabled',
  'auth.mfa_disabled': 'MFA disabled',
  'auth.mfa_verify': 'MFA verified',
  'auth.session_revoked': 'Session revoked',
  'auth.sessions_revoked': 'All other sessions revoked',
  'auth.register': 'Account created',
  'auth.email_verified': 'Email verified',
  'auth.oauth_login': 'Signed in via Google',
  'auth.oauth_register': 'Registered via Google',
}

const EVENT_SEVERITY: Record<string, 'high' | 'medium' | 'low'> = {
  'auth.login_failed': 'high',
  'auth.mfa_disabled': 'high',
  'auth.password_changed': 'medium',
  'auth.password_reset': 'medium',
  'auth.sessions_revoked': 'medium',
  'auth.session_revoked': 'medium',
  'auth.mfa_enabled': 'low',
}

function severityDot(action: string): string {
  const sev = EVENT_SEVERITY[action]
  if (sev === 'high') return 'bg-red-500'
  if (sev === 'medium') return 'bg-amber-500'
  return 'bg-emerald-500'
}

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(ts).toLocaleDateString()
}

/* ── Main Page ── */

export default function SecurityPage() {
  const { mfa_enrolled, workspace_auth_policy, permissions, refresh } = useAuth()
  const isAdmin = permissions.can_admin

  const [sessions, setSessions] = useState<Session[]>([])
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null)
  const [events, setEvents] = useState<SecurityEvent[]>([])
  const [loading, setLoading] = useState(true)

  const loadAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/auth/sessions', { credentials: 'include' }).then((r) => (r.ok ? r.json() : { sessions: [] })),
      fetch('/api/auth/mfa/status', { credentials: 'include' }).then((r) => (r.ok ? r.json() : { enabled: false })),
      isAdmin
        ? fetch('/api/audit/events?action=auth.&since_hours=720&page_size=20', { credentials: 'include' }).then((r) => (r.ok ? r.json() : { items: [] }))
        : Promise.resolve({ items: [] }),
    ])
      .then(([sessData, mfaData, eventsData]) => {
        setSessions(sessData.sessions || [])
        setMfaStatus(mfaData as MfaStatus)
        setEvents((eventsData.items || []) as SecurityEvent[])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [isAdmin])

  useEffect(() => { loadAll() }, [loadAll])

  const mfaEnabled = mfaStatus?.enabled ?? mfa_enrolled ?? false
  const sessionCount = sessions.length
  const otherSessions = sessions.filter((s) => !s.current)

  /* ── Security Health Score ── */
  type RiskLevel = 'low' | 'medium' | 'high'
  const warnings: string[] = []
  if (!mfaEnabled) warnings.push('Two-factor authentication is not enabled')
  if (otherSessions.length > 5) warnings.push(`${otherSessions.length} other active sessions detected`)
  if (workspace_auth_policy && !workspace_auth_policy.mfa_required && isAdmin)
    warnings.push('Workspace does not require MFA for all members')

  let riskLevel: RiskLevel = 'low'
  if (warnings.length >= 2) riskLevel = 'high'
  else if (warnings.length === 1) riskLevel = 'medium'

  const riskConfig = {
    low: { label: 'Good', color: '#10b981', bg: 'bg-emerald-500/10 border-emerald-500/20', icon: '✅' },
    medium: { label: 'Fair', color: '#eab308', bg: 'bg-yellow-500/10 border-yellow-500/20', icon: '⚠️' },
    high: { label: 'At Risk', color: '#ef4444', bg: 'bg-red-500/10 border-red-500/20', icon: '🔴' },
  }
  const risk = riskConfig[riskLevel]

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Account Security</h1>
        <Card className="p-6 text-center text-[var(--tc-muted)]">Loading security information...</Card>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Account Security</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">
          Your account security at a glance, with clear actions to improve it.
        </p>
      </div>

      {/* ── Section 1: Security Health ── */}
      <Card className={`p-5 border ${risk.bg}`}>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">{risk.icon}</span>
          <div>
            <div className="text-sm font-semibold" style={{ color: risk.color }}>
              Security Status: {risk.label}
            </div>
            <div className="text-xs text-[var(--tc-muted)]">
              {warnings.length === 0
                ? 'Your account security looks good. No immediate actions needed.'
                : `${warnings.length} issue${warnings.length > 1 ? 's' : ''} found that could improve your security.`}
            </div>
          </div>
        </div>
        {warnings.length > 0 && (
          <div className="space-y-1.5 mt-2">
            {warnings.map((w, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className="mt-0.5 inline-block w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
                <span className="text-[var(--tc-text)]">{w}</span>
              </div>
            ))}
          </div>
        )}
        {!mfaEnabled && (
          <div className="mt-3 pt-3 border-t border-white/10">
            <p className="text-xs text-[var(--tc-muted)] mb-2">
              Enabling two-factor authentication is the single most effective way to protect your account.
            </p>
          </div>
        )}
      </Card>

      {/* ── Section 2: Account Security ── */}
      <div className="grid gap-4 md:grid-cols-2">
        <MfaSection mfaEnabled={mfaEnabled} onUpdate={() => { loadAll(); refresh() }} />
        <PasswordSection onSessionsChanged={loadAll} />
      </div>

      {/* ── Section 3: Workspace Security Policy (admin only) ── */}
      {isAdmin && <WorkspacePolicySection />}

      {/* ── Section 4: Sessions ── */}
      <SessionsSection sessions={sessions} otherSessions={otherSessions} onReload={loadAll} />

      {/* ── Section 5: Security Activity ── */}
      {events.length > 0 && <SecurityActivitySection events={events} />}
    </div>
  )
}

/* ── Section 2a: MFA ── */

function MfaSection({ mfaEnabled, onUpdate }: { mfaEnabled: boolean; onUpdate: () => void }) {
  const [step, setStep] = useState<'idle' | 'qr' | 'recovery' | 'disable'>('idle')
  const [secret, setSecret] = useState('')
  const [confirmCode, setConfirmCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [disablePassword, setDisablePassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const startSetup = async () => {
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/mfa/setup', { method: 'POST', credentials: 'include' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Failed to start setup'); return }
      setSecret(data.secret || '')
      setStep('qr')
      setConfirmCode('')
    } finally { setSubmitting(false) }
  }

  const confirmMfa = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/mfa/confirm', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: confirmCode }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Invalid code'); return }
      setRecoveryCodes(data.recovery_codes || [])
      setStep('recovery')
    } finally { setSubmitting(false) }
  }

  const finishSetup = () => {
    setStep('idle')
    setSecret('')
    setRecoveryCodes([])
    setConfirmCode('')
    onUpdate()
  }

  const disableMfa = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/mfa/disable', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: disablePassword }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Failed to disable'); return }
      setDisablePassword('')
      setStep('idle')
      onUpdate()
    } finally { setSubmitting(false) }
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-base">🔐</span>
        <h3 className="text-sm font-semibold text-[var(--tc-text)]">Two-Factor Authentication</h3>
      </div>

      {step === 'qr' ? (
        <div>
          <p className="text-xs text-[var(--tc-muted)] mb-2">
            Add this secret to your authenticator app (Google Authenticator, Authy, etc.):
          </p>
          <p className="font-mono text-xs bg-white/5 p-2.5 rounded border border-[var(--tc-border)] mb-3 break-all select-all">
            {secret}
          </p>
          <form onSubmit={confirmMfa} className="space-y-2">
            <Input
              type="text" inputMode="numeric" autoComplete="one-time-code"
              placeholder="Enter 6-digit code" value={confirmCode}
              onChange={(e) => setConfirmCode(e.target.value)} maxLength={6} required
            />
            {error && <p className="text-xs text-[var(--tc-danger)]">{error}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={submitting}>{submitting ? 'Verifying...' : 'Verify & Enable'}</Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => { setStep('idle'); setError('') }}>Cancel</Button>
            </div>
          </form>
        </div>
      ) : step === 'recovery' ? (
        <div>
          <p className="text-xs text-[var(--tc-muted)] mb-2">
            Save these recovery codes in a safe place. Each can be used once if you lose your authenticator.
          </p>
          <div className="font-mono text-xs bg-white/5 p-3 rounded border border-[var(--tc-border)] mb-3 space-y-0.5 select-all">
            {recoveryCodes.map((c, i) => <div key={i}>{c}</div>)}
          </div>
          <Button size="sm" onClick={finishSetup}>I've saved these codes</Button>
        </div>
      ) : step === 'disable' ? (
        <form onSubmit={disableMfa} className="space-y-2">
          <p className="text-xs text-[var(--tc-muted)]">Enter your password to disable two-factor authentication.</p>
          <Input type="password" autoComplete="current-password" placeholder="Your password"
            value={disablePassword} onChange={(e) => setDisablePassword(e.target.value)} required />
          {error && <p className="text-xs text-[var(--tc-danger)]">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" variant="ghost" className="text-red-400" disabled={submitting}>
              {submitting ? 'Disabling...' : 'Disable MFA'}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setStep('idle'); setError('') }}>Cancel</Button>
          </div>
        </form>
      ) : (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className={`inline-block w-2 h-2 rounded-full ${mfaEnabled ? 'bg-emerald-500' : 'bg-red-500'}`} />
            <span className="text-sm text-[var(--tc-text)]">
              {mfaEnabled ? 'Enabled' : 'Not enabled'}
            </span>
          </div>
          <p className="text-xs text-[var(--tc-muted)] mb-3">
            {mfaEnabled
              ? 'Your account is protected with an authenticator app.'
              : 'Add an extra layer of security by requiring a code from your phone when signing in.'}
          </p>
          {mfaEnabled ? (
            <Button size="sm" variant="ghost" className="text-red-400" onClick={() => setStep('disable')}>
              Disable MFA
            </Button>
          ) : (
            <Button size="sm" onClick={startSetup} disabled={submitting}>
              {submitting ? 'Starting...' : 'Enable MFA'}
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}

/* ── Section 2b: Password ── */

function PasswordSection({ onSessionsChanged }: { onSessionsChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [invalidateOthers, setInvalidateOthers] = useState(false)
  const [changing, setChanging] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleChange = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setSuccess('')
    if (newPw !== confirm) { setError('Passwords do not match.'); return }
    if (newPw.length < 6) { setError('Must be at least 6 characters.'); return }
    setChanging(true)
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: current, new_password: newPw, invalidate_other_sessions: invalidateOthers }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Failed to change password.'); return }
      setSuccess('Password updated successfully.')
      setCurrent(''); setNewPw(''); setConfirm('')
      if (invalidateOthers) onSessionsChanged()
      setInvalidateOthers(false)
      setTimeout(() => { setSuccess(''); setOpen(false) }, 2000)
    } finally { setChanging(false) }
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-base">🔑</span>
        <h3 className="text-sm font-semibold text-[var(--tc-text)]">Password</h3>
      </div>
      {!open ? (
        <div>
          <p className="text-xs text-[var(--tc-muted)] mb-3">
            Use a strong, unique password that you don't use on other sites.
          </p>
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Change Password</Button>
        </div>
      ) : (
        <form onSubmit={handleChange} className="space-y-2">
          <Input type="password" autoComplete="current-password" placeholder="Current password"
            value={current} onChange={(e) => setCurrent(e.target.value)} required />
          <Input type="password" autoComplete="new-password" placeholder="New password"
            value={newPw} onChange={(e) => setNewPw(e.target.value)} required minLength={6} />
          <Input type="password" autoComplete="new-password" placeholder="Confirm new password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} required minLength={6} />
          <label className="flex items-center gap-2 text-xs text-[var(--tc-muted)] cursor-pointer">
            <input type="checkbox" checked={invalidateOthers} onChange={(e) => setInvalidateOthers(e.target.checked)} />
            Sign out all other sessions
          </label>
          {error && <p className="text-xs text-[var(--tc-danger)]">{error}</p>}
          {success && <p className="text-xs text-emerald-400">{success}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={changing}>{changing ? 'Updating...' : 'Update Password'}</Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => { setOpen(false); setError('') }}>Cancel</Button>
          </div>
        </form>
      )}
    </Card>
  )
}

/* ── Section 3: Workspace Security Policy ── */

function WorkspacePolicySection() {
  const [policy, setPolicy] = useState<{ mfa_required: boolean; session_max_age_seconds: number | null } | null>(null)
  const [mfaReq, setMfaReq] = useState(false)
  const [sessionDays, setSessionDays] = useState<number | ''>('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch('/api/workspaces/current', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d) {
          setPolicy(d)
          setMfaReq(d.mfa_required)
          setSessionDays(d.session_max_age_seconds != null ? Math.round(d.session_max_age_seconds / 86400) : '')
        }
      })
      .catch(() => {})
  }, [])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    const sessionMax = sessionDays === '' || sessionDays === 0
      ? null
      : Math.min(90, Math.max(1, Number(sessionDays))) * 86400
    try {
      const res = await fetch('/api/workspaces/current', {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mfa_required: mfaReq, session_max_age_seconds: sessionMax }),
      })
      if (res.ok) {
        const d = await res.json()
        setPolicy(d)
        setSaved(true)
        setTimeout(() => setSaved(false), 2000)
      }
    } finally { setSaving(false) }
  }

  if (!policy) return null

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base">🏢</span>
        <h3 className="text-sm font-semibold text-[var(--tc-text)]">Workspace Security Policy</h3>
      </div>
      <p className="text-xs text-[var(--tc-muted)] mb-4">These settings apply to all members of this workspace.</p>
      <form onSubmit={save} className="space-y-4 max-w-md">
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative">
            <input type="checkbox" checked={mfaReq} onChange={(e) => setMfaReq(e.target.checked)} className="sr-only peer" />
            <div className="h-5 w-9 rounded-full bg-white/10 peer-checked:bg-[var(--tc-primary)] transition-colors" />
            <div className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white/80 transition-transform peer-checked:translate-x-4" />
          </div>
          <div>
            <span className="text-xs font-medium text-[var(--tc-text)]">Require MFA for all members</span>
            <p className="text-[10px] text-[var(--tc-muted)] mt-0.5">Members must enable two-factor authentication to access this workspace.</p>
          </div>
        </label>

        <div>
          <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Session lifetime (days)</label>
          <input
            type="number" min={1} max={90} placeholder="7 (default)"
            value={sessionDays}
            onChange={(e) => setSessionDays(e.target.value === '' ? '' : e.target.valueAsNumber)}
            className="w-40 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-[var(--tc-text)] outline-none focus:border-[var(--tc-primary)]"
          />
          <p className="text-[10px] text-[var(--tc-muted)] mt-1">Leave empty for default (7 days). Maximum 90 days.</p>
        </div>

        <div className="flex items-center gap-2">
          <Button type="submit" size="sm" disabled={saving}>{saving ? 'Saving...' : 'Save Policy'}</Button>
          {saved && <span className="text-xs text-emerald-400">Saved</span>}
        </div>
      </form>
    </Card>
  )
}

/* ── Section 4: Sessions ── */

function SessionsSection({ sessions, otherSessions, onReload }: {
  sessions: Session[]
  otherSessions: Session[]
  onReload: () => void
}) {
  const [revoking, setRevoking] = useState(false)
  const [error, setError] = useState('')

  const revokeOthers = async () => {
    if (!confirm('Sign out all other sessions? You will stay signed in on this device.')) return
    setError('')
    setRevoking(true)
    try {
      const res = await fetch('/api/auth/sessions/revoke-others', { method: 'POST', credentials: 'include' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Failed'); return }
      onReload()
    } finally { setRevoking(false) }
  }

  const currentSession = sessions.find((s) => s.current)
  const others = sessions.filter((s) => !s.current)

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-base">💻</span>
          <h3 className="text-sm font-semibold text-[var(--tc-text)]">Active Sessions</h3>
        </div>
        <span className="text-xs text-[var(--tc-muted)]">
          {sessions.length} active session{sessions.length !== 1 ? 's' : ''}
        </span>
      </div>
      <p className="text-xs text-[var(--tc-muted)] mb-4">
        Devices and browsers where your account is currently signed in.
      </p>

      <div className="space-y-2">
        {/* Current session first */}
        {currentSession && <SessionRow session={currentSession} isCurrent />}

        {/* Other sessions */}
        {others.map((s) => <SessionRow key={s.id} session={s} isCurrent={false} />)}
      </div>

      {otherSessions.length > 0 && (
        <div className="mt-4 pt-3 border-t border-white/10">
          <Button size="sm" variant="ghost" className="text-red-400" onClick={revokeOthers} disabled={revoking}>
            {revoking ? 'Signing out...' : `Sign out all other devices (${otherSessions.length})`}
          </Button>
        </div>
      )}
      {error && <p className="mt-2 text-xs text-[var(--tc-danger)]">{error}</p>}
    </Card>
  )
}

function SessionRow({ session, isCurrent }: { session: Session; isCurrent: boolean }) {
  const { browser, os, device } = parseUA(session.user_agent)

  const deviceIcon = /Windows/i.test(os) ? '🖥️'
    : /mac/i.test(os) ? '💻'
    : /Linux/i.test(os) ? '🐧'
    : /Android/i.test(os) ? '📱'
    : /iOS/i.test(os) ? '📱'
    : /Server/i.test(os) ? '⚙️'
    : '💻'

  return (
    <div className={`flex items-center gap-3 rounded-lg border p-3 ${isCurrent ? 'border-[var(--tc-primary)]/30 bg-[var(--tc-primary)]/5' : 'border-[var(--tc-border)]'}`}>
      <span className="text-lg flex-shrink-0">{deviceIcon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--tc-text)] truncate">{device}</span>
          {isCurrent && (
            <span className="inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0 text-[9px] font-medium text-emerald-400">
              This device
            </span>
          )}
        </div>
        <div className="text-[10px] text-[var(--tc-muted)] mt-0.5">
          {session.ip_address || 'Unknown IP'} · {session.created_at ? timeAgo(session.created_at) : 'Unknown time'}
        </div>
      </div>
    </div>
  )
}

/* ── Section 5: Security Activity ── */

function SecurityActivitySection({ events }: { events: SecurityEvent[] }) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? events : events.slice(0, 8)

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base">📋</span>
        <h3 className="text-sm font-semibold text-[var(--tc-text)]">Security Activity</h3>
      </div>
      <p className="text-xs text-[var(--tc-muted)] mb-3">Recent authentication and security events in your workspace.</p>

      <div className="space-y-1.5">
        {visible.map((ev) => {
          const label = EVENT_LABELS[ev.action] || ev.action.replace(/\./g, ' ').replace(/^auth /, '')
          return (
            <div key={ev.id} className="flex items-center gap-2.5 py-1.5 border-b border-white/5 last:border-0">
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${severityDot(ev.action)}`} />
              <span className="text-xs text-[var(--tc-text)] flex-1 truncate">{label}</span>
              {ev.email && <span className="text-[10px] text-[var(--tc-muted)] truncate max-w-[140px]">{ev.email}</span>}
              <span className="text-[10px] text-[var(--tc-muted)] flex-shrink-0">{timeAgo(ev.occurred_at)}</span>
            </div>
          )
        })}
      </div>

      {events.length > 8 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-2 text-xs text-[var(--tc-soft)] hover:text-[var(--tc-text)] transition-colors"
        >
          {showAll ? 'Show less' : `Show all ${events.length} events`}
        </button>
      )}
    </Card>
  )
}
