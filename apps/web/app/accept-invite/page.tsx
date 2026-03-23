'use client'

import { Suspense, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Card, Button, Input } from '@/components/ui'

function AcceptInviteContent() {
  const searchParams = useSearchParams()
  const tokenFromUrl = searchParams.get('token') ?? ''

  const [step, setStep] = useState<'verify' | 'accept'>(() => (tokenFromUrl.trim() ? 'accept' : 'verify'))
  const [email, setEmail] = useState('')
  const [verificationCode, setVerificationCode] = useState('')
  const [token, setToken] = useState(tokenFromUrl.trim())
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [verifying, setVerifying] = useState(false)

  const onVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setVerifying(true)
    const res = await fetch('/api/auth/verify-invite-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.trim().toLowerCase(),
        code: verificationCode.trim(),
      }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    setVerifying(false)
    if (!res.ok) {
      setError(Array.isArray(data.detail) ? data.detail[0]?.msg ?? data.detail : data.detail || 'Verification failed')
      return
    }
    if (!data.token || typeof data.token !== 'string') {
      setError('Unexpected response. Please try again.')
      return
    }
    setToken(data.token)
    setStep('accept')
  }

  const onSubmitAccept = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const pw = password.trim()
    if (pw && pw.length < 6) {
      setError('Password must be at least 6 characters for new accounts.')
      return
    }
    const res = await fetch('/api/auth/accept-invite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token.trim(), password: pw || undefined }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(Array.isArray(data.detail) ? data.detail[0]?.msg ?? data.detail : data.detail || 'Accept failed')
      return
    }
    setSuccess(true)
  }

  const loginHref = email
    ? `/login?email=${encodeURIComponent(email.trim().toLowerCase())}`
    : '/login'

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">You are in!</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">
            You have joined the workspace. Sign in with your email and the password you just set.
          </p>
          <Link href={loginHref} className="mt-4 inline-block">
            <Button>Sign in</Button>
          </Link>
        </Card>
      </main>
    )
  }

  if (step === 'verify') {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Verify your invitation</h1>
          <p className="mt-2 mb-6 text-sm text-[var(--tc-muted)]">
            Enter the email address the invite was sent to and the verification code from your email. Then you can set
            a password (new accounts) or finish joining (existing accounts).
          </p>
          <form onSubmit={onVerify} className="space-y-4">
            <Input
              label="Email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
            />
            <Input
              label="Verification code"
              autoComplete="one-time-code"
              required
              value={verificationCode}
              onChange={(e) => setVerificationCode(e.target.value)}
              placeholder="e.g. AB12-CD34-EF56"
            />
            {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
            <Button type="submit" className="w-full" disabled={verifying}>
              {verifying ? 'Verifying...' : 'Continue'}
            </Button>
          </form>
          <p className="mt-4 text-sm text-[var(--tc-muted)]">
            <Link href="/login" className="text-[var(--tc-soft)] underline">
              Back to sign in
            </Link>
          </p>
        </Card>
      </main>
    )
  }

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Invalid link</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">This invitation is missing or invalid. Verify your email and code first.</p>
          <button type="button" className="mt-4" onClick={() => setStep('verify')}>
            <Button variant="secondary">Enter verification code</Button>
          </button>
          <p className="mt-4">
            <Link href="/login" className="text-sm text-[var(--tc-soft)] underline">
              Back to sign in
            </Link>
          </p>
        </Card>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-[var(--tc-text)]">Accept invitation</h1>
        <p className="mt-2 mb-6 text-sm text-[var(--tc-muted)]">
          If you do not have an account yet, set a password to create one. If you already have an account, leave password
          blank and submit to join the workspace.
        </p>
        <form onSubmit={onSubmitAccept} className="space-y-4">
          <Input
            label="Password (for new accounts)"
            type="password"
            autoComplete="new-password"
            placeholder="Min 6 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full">
            Accept invitation
          </Button>
        </form>
        <p className="mt-4 text-sm text-[var(--tc-muted)]">
          <button type="button" className="text-[var(--tc-soft)] underline" onClick={() => { setStep('verify'); setToken(''); setError('') }}>
            Use a different code
          </button>
          {' | '}
          <Link href="/login" className="text-[var(--tc-soft)] underline">
            Back to sign in
          </Link>
        </p>
      </Card>
    </main>
  )
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center p-4"><p className="text-[var(--tc-muted)]">Loading...</p></main>}>
      <AcceptInviteContent />
    </Suspense>
  )
}
