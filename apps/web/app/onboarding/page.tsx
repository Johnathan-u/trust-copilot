'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Card, Button, Input } from '@/components/ui'

export default function OnboardingPage() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Please enter a workspace name.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/workspaces', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed }),
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Could not create workspace')
        return
      }
      router.push('/dashboard')
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setLoading(false)
    }
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
          <h1 className="text-xl font-bold text-[var(--tc-text)]">Welcome to Trust Copilot</h1>
        </div>
        <p className="mb-6 text-sm text-[var(--tc-muted)]">
          Name your workspace. This is where your team's documents, questionnaires, and compliance data will live.
        </p>
        <form onSubmit={onSubmit} className="space-y-4">
          <Input
            label="Workspace name"
            type="text"
            autoComplete="organization"
            placeholder="e.g. Acme Corp"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Creating…' : 'Create workspace'}
          </Button>
        </form>
      </Card>
    </main>
  )
}
