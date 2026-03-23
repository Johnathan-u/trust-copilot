'use client'

import { Suspense, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Card, Button, Input } from '@/components/ui'

function ResetPasswordContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const res = await fetch('/api/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: password }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(data.detail || 'Reset failed')
      return
    }
    setSuccess(true)
  }

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Password updated</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">You can sign in with your new password.</p>
          <Link href="/login" className="mt-4 inline-block">
            <Button>Sign in</Button>
          </Link>
        </Card>
      </main>
    )
  }

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Invalid link</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">This reset link is missing or invalid.</p>
          <Link href="/forgot-password" className="mt-4 inline-block">
            <Button variant="ghost">Request a new link</Button>
          </Link>
        </Card>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-[var(--tc-text)]">Set new password</h1>
        <p className="mt-2 mb-6 text-sm text-[var(--tc-muted)]">Enter your new password below.</p>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
          />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full">
            Update password
          </Button>
        </form>
        <p className="mt-4 text-sm text-[var(--tc-muted)]">
          <Link href="/login" className="text-[var(--tc-soft)] underline">Back to sign in</Link>
        </p>
      </Card>
    </main>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center p-4"><p className="text-[var(--tc-muted)]">Loading…</p></main>}>
      <ResetPasswordContent />
    </Suspense>
  )
}
