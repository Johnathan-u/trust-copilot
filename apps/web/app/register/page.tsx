'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Card, Button, Input } from '@/components/ui'

export default function RegisterPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: displayName || null }),
      credentials: 'include',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      setError(data.detail || 'Registration failed')
      return
    }
    setSuccess(true)
  }

  if (success) {
    return (
      <main className="flex min-h-screen items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Check your email</h1>
          <p className="mt-2 text-sm text-[var(--tc-muted)]">
            If that email is not yet registered, you will receive a verification link. Click it to verify, then sign in.
          </p>
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
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Create account</h1>
        </div>
        <p className="mb-6 text-sm text-[var(--tc-muted)]">
          Register with your email. You will receive a verification link.
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
            label="Display name (optional)"
            type="text"
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          <Input
            label="Password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full">
            Register
          </Button>
        </form>
        <p className="mt-4 text-sm text-[var(--tc-muted)]">
          <Link href="/#features" className="text-[var(--tc-soft)] underline">Features</Link>
          {' · '}
          <Link href="/pricing" className="text-[var(--tc-soft)] underline">Pricing</Link>
        </p>
      </Card>
    </main>
  )
}
