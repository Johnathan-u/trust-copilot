'use client'

import { Suspense, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Card, Button, Input } from '@/components/ui'

type OAuthProviders = { google: boolean; github: boolean; microsoft?: boolean; sso?: boolean; idme?: boolean }

function LoginContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const next = searchParams.get('next') || '/dashboard'
  const prefillEmail = searchParams.get('email') || ''
  const [email, setEmail] = useState(prefillEmail)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [mfaStep, setMfaStep] = useState<boolean>(false)
  const [mfaToken, setMfaToken] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  // Default to showing Google and GitHub so buttons are visible; API can hide if not configured
  const [oauthProviders, setOauthProviders] = useState<OAuthProviders>({ google: true, github: true, sso: false })

  useEffect(() => {
    fetch('/api/auth/oauth/providers', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: OAuthProviders | null) => {
        if (d && typeof d === 'object') setOauthProviders({ google: true, github: true, sso: false, ...d })
      })
      .catch(() => {})
  }, [])

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, remember_me: rememberMe }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (data.requires_mfa && data.mfa_token) {
      setMfaToken(data.mfa_token)
      setMfaStep(true)
      return
    }
    if (!res.ok) {
      if (res.status === 429) {
        setError('Too many attempts. Try again later.')
        return
      }
      const msg = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail
      setError(msg || `Login failed (${res.status})`)
      return
    }
    router.push(next)
  }

  const onMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const res = await fetch('/api/auth/mfa/verify-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mfa_token: mfaToken, code: mfaCode, remember_me: rememberMe }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      if (res.status === 429) setError('Too many attempts. Try again later.')
      else setError(Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail || 'Invalid code')
      return
    }
    router.push(next)
  }

  if (mfaStep) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Two-factor authentication</h1>
          <p className="mt-2 mb-6 text-sm text-[var(--tc-muted)]">
            Enter the 6-digit code from your authenticator app, or a recovery code.
          </p>
          <form onSubmit={onMfaSubmit} className="space-y-4">
            <Input
              label="Code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000 or recovery code"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
              required
            />
            {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
            <Button type="submit" className="w-full">
              Verify
            </Button>
          </form>
          <Button
            type="button"
            variant="ghost"
            className="mt-4"
            onClick={() => { setMfaStep(false); setMfaToken(''); setMfaCode(''); setError(''); }}
          >
            Back to sign in
          </Button>
        </Card>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <div className="mb-2 flex items-center gap-3">
          <div
            className="grid h-10 w-10 place-items-center rounded-xl text-lg font-bold text-white"
            style={{
              background: 'linear-gradient(135deg, #7c96ff, #5b7cff 55%, #2dd4bf)',
              boxShadow: '0 12px 30px rgba(91,124,255,0.35)',
            }}
          >
            ✓
          </div>
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Trust Copilot</h1>
        </div>
        <p className="mb-6 text-sm text-[var(--tc-muted)]">
          Answer compliance questionnaires with AI and evidence.
        </p>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <Input
            label="Password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--tc-muted)]">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="h-4 w-4 rounded border-[var(--tc-border)] bg-white/5 accent-[var(--tc-primary)]"
            />
            Keep me signed in
          </label>
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full">
            Sign in
          </Button>
          {(oauthProviders.google || oauthProviders.github || oauthProviders.sso) && (
            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[var(--tc-border)]" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="bg-[var(--tc-panel)] px-2 text-[var(--tc-muted)]">or continue with</span>
              </div>
            </div>
          )}
          <div className="flex flex-col gap-3 mt-2">
            {oauthProviders.sso && (
              <a
                href="/api/auth/sso"
                className="flex items-center justify-center gap-2 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-3 text-sm font-medium text-[var(--tc-text)] hover:bg-white/10 transition-colors min-h-[44px]"
              >
                Sign in with SSO
              </a>
            )}
            {oauthProviders.google && (
              <a
                href="/api/auth/oauth/google"
                className="flex items-center justify-center gap-2 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-3 text-sm font-medium text-[var(--tc-text)] hover:bg-white/10 transition-colors min-h-[44px]"
              >
                <svg className="h-5 w-5 shrink-0" viewBox="0 0 24 24"><path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                Sign in with Google
              </a>
            )}
            {oauthProviders.github && (
              <a
                href="/api/auth/oauth/github"
                className="flex items-center justify-center gap-2 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-3 text-sm font-medium text-[var(--tc-text)] hover:bg-white/10 transition-colors min-h-[44px]"
              >
                <svg className="h-5 w-5 shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/></svg>
                Sign in with GitHub
              </a>
            )}
          </div>
        </form>
        <p className="mt-4 text-sm text-[var(--tc-muted)]">
          <Link href="/register" prefetch={false} className="text-[var(--tc-soft)] underline">Create account</Link>
          {' · '}
          <Link href="/forgot-password" prefetch={false} className="text-[var(--tc-soft)] underline">Forgot password?</Link>
        </p>
        {process.env.NEXT_PUBLIC_SHOW_DEMO_HINT === 'true' && (
          <p className="mt-2 text-xs text-[var(--tc-muted)]">Demo: demo@trust.local / j</p>
        )}
      </Card>
    </main>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center p-4"><p className="text-[var(--tc-muted)]">Loading…</p></main>}>
      <LoginContent />
    </Suspense>
  )
}
