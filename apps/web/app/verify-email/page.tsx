'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Card, Button } from '@/components/ui'

function VerifyEmailContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [message, setMessage] = useState('')

  const called = useRef(false)
  useEffect(() => {
    if (!token) {
      setStatus('error')
      setMessage('Missing verification link.')
      return
    }
    if (called.current) return
    called.current = true
    fetch(`/api/auth/verify-email?token=${encodeURIComponent(token)}`, {
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
  }, [token])

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <h1 className="text-xl font-bold text-[var(--tc-text)]">Email verification</h1>
        {status === 'loading' && <p className="mt-2 text-sm text-[var(--tc-muted)]">Verifying…</p>}
        {status === 'ok' && <p className="mt-2 text-sm text-[var(--tc-muted)]">{message}</p>}
        {status === 'error' && <p className="mt-2 text-sm text-[var(--tc-danger)]">{message}</p>}
        <Link href="/login" className="mt-4 inline-block">
          <Button>Sign in</Button>
        </Link>
      </Card>
    </main>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center p-4"><p className="text-[var(--tc-muted)]">Verifying…</p></main>}>
      <VerifyEmailContent />
    </Suspense>
  )
}
