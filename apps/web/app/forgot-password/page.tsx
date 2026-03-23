'use client'

import { useState } from 'react'
import Link from 'next/link'
import { Card, Button, Input } from '@/components/ui'
import { formatApiErrorDetail } from '@/lib/api-error'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [devResetUrl, setDevResetUrl] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const res = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
        credentials: 'include',
      })
      const data = (await res.json().catch(() => ({}))) as Record<string, unknown>
      if (!res.ok) {
        setError(formatApiErrorDetail(data, 'Request failed'))
        return
      }
      if (typeof data.reset_url === 'string' && data.reset_url.startsWith('http')) {
        setDevResetUrl(data.reset_url)
      }
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Check your email</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">
            If that email is registered, you will receive a reset link shortly.
          </p>
          {devResetUrl && (
            <div className="mt-4 rounded-xl border border-[var(--tc-border)] bg-white/5 p-3 text-sm">
              <p className="font-medium text-[var(--tc-text)]">Development mode</p>
              <p className="mt-1 text-[var(--tc-muted)]">
                Reset link (only when API has TRUST_COPILOT_DEV_RETURN_RESET_URL enabled):
              </p>
              <a
                href={devResetUrl}
                className="mt-2 block break-all text-[var(--tc-soft)] underline"
              >
                {devResetUrl}
              </a>
            </div>
          )}
          <Link href="/login" className="mt-4 inline-block">
            <Button variant="ghost">Back to sign in</Button>
          </Link>
        </Card>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-[var(--tc-text)]">Forgot password</h1>
        <p className="mt-2 mb-6 text-sm text-[var(--tc-muted)]">
          Enter your email and we will send you a reset link.
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
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? 'Sending…' : 'Send reset link'}
          </Button>
        </form>
        <p className="mt-4 text-sm text-[var(--tc-muted)]">
          <Link href="/login" className="text-[var(--tc-soft)] underline">Back to sign in</Link>
        </p>
      </Card>
    </main>
  )
}
