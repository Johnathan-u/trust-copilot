'use client'

import Link from 'next/link'

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4">
      <h1 className="mb-6 text-2xl font-bold text-[var(--tc-text)]">Trust Copilot</h1>
      <p className="mb-6 text-sm text-[var(--tc-muted)]">
        Answer compliance questionnaires with AI and evidence.
      </p>
      <div className="flex gap-3">
        <Link
          href="/login"
          className="rounded-xl border border-[rgba(124,150,255,0.5)] px-5 py-2.5 font-semibold text-white transition hover:opacity-95"
          style={{
            background: 'linear-gradient(135deg, var(--tc-primary-2), var(--tc-primary))',
            boxShadow: '0 12px 28px rgba(91,124,255,0.28)',
          }}
        >
          Sign in
        </Link>
        <Link
          href="/dashboard"
          className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-5 py-2.5 font-medium text-[var(--tc-text)] transition hover:bg-white/10"
        >
          Dashboard
        </Link>
        <Link
          href="/trust"
          className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-5 py-2.5 font-medium text-[var(--tc-text)] transition hover:bg-white/10"
        >
          Trust Center
        </Link>
      </div>
    </main>
  )
}
