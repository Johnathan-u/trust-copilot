'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Card, Button, Input } from '@/components/ui'
import { formatApiErrorDetail } from '@/lib/api-error'
import { verificationWithoutToken } from '@/lib/render-state'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'

function VerifyEmailContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const userId = searchParams.get('user')
  const initialToken = verificationWithoutToken(token && userId ? token : null)
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>(
    initialToken.status
  )
  const [message, setMessage] = useState(initialToken.message)
  const tokenKey = useKeyedGeneration(token ?? '', { runOnMount: false })
  if (tokenKey.changed && !token) {
    const missing = verificationWithoutToken(null)
    setStatus(missing.status)
    setMessage(missing.message)
  }

  const [codeEmail, setCodeEmail] = useState('')
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState('')
  const [codeBusy, setCodeBusy] = useState(false)

  const onSubmitCode = async (event: React.FormEvent) => {
    event.preventDefault()
    setCodeBusy(true)
    setCodeError('')
    try {
      const response = await fetch('/api/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: codeEmail, code }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setCodeError(formatApiErrorDetail(data, 'Invalid code'))
        return
      }
      setStatus('ok')
      setMessage(
        typeof data.message === 'string' && data.message
          ? data.message
          : 'Email verified.'
      )
    } catch {
      setCodeError('Verification failed.')
    } finally {
      setCodeBusy(false)
    }
  }

  const called = useRef(false)
  useEffect(() => {
    if (!token || !userId) return
    if (called.current) return
    called.current = true
    const params = new URLSearchParams({ token, user: userId })
    fetch(`/api/auth/verify-email?${params.toString()}`, {
      method: 'POST',
      credentials: 'include',
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.message) {
          setStatus('ok')
          setMessage(d.message)
        } else {
          setStatus('error')
          setMessage(d.detail || 'Verification failed.')
        }
      })
      .catch(() => {
        setStatus('error')
        setMessage('Verification failed.')
      })
  }, [token, userId])

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-[var(--tc-text)]">
          Email verification
        </h1>
        {status === 'loading' && (
          <p className="mt-2 text-sm text-[var(--tc-muted)]">Verifying…</p>
        )}
        {status === 'ok' && (
          <p className="mt-2 text-sm text-[var(--tc-muted)]">{message}</p>
        )}
        {status === 'error' && (
          <p className="mt-2 text-sm text-[var(--tc-danger)]">{message}</p>
        )}
        <form onSubmit={onSubmitCode} className="mt-4 space-y-4">
          <p className="text-sm text-[var(--tc-muted)]">
            Or enter the 6-digit code from the verification email.
          </p>
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            value={codeEmail}
            onChange={(event) => setCodeEmail(event.target.value)}
            required
          />
          <Input
            label="Verification code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="6-digit code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            maxLength={6}
            required
          />
          {codeError && (
            <p className="text-sm text-[var(--tc-danger)]">{codeError}</p>
          )}
          <Button type="submit" className="w-full" disabled={codeBusy}>
            {codeBusy ? 'Checking…' : 'Verify code'}
          </Button>
        </form>
        <Link href="/login" className="mt-4 inline-block">
          <Button>Sign in</Button>
        </Link>
      </Card>
    </main>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center p-4">
          <p className="text-[var(--tc-muted)]">Verifying…</p>
        </main>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  )
}
