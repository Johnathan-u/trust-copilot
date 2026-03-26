'use client'

import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'

const monthlyPrice = 25
const annualPrice = 250

function CheckItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-sm text-[var(--tc-muted)]">
      <span className="mt-0.5 text-[var(--tc-success)]">&#10003;</span>
      <span>{children}</span>
    </li>
  )
}

function StepIndicator({ current }: { current: number }) {
  const steps = ['Plan', 'Account', 'Verify', 'Workspace']
  return (
    <div className="mx-auto mb-8 flex max-w-sm items-center justify-center gap-0">
      {steps.map((label, i) => (
        <div key={label} className="flex items-center">
          <div className="flex flex-col items-center">
            <div
              className={`grid h-8 w-8 place-items-center rounded-full text-xs font-bold transition-all duration-300 ${
                i < current
                  ? 'bg-[var(--tc-success)] text-white'
                  : i === current
                    ? 'bg-[var(--tc-primary)] text-white shadow-[0_0_16px_rgba(91,124,255,0.4)]'
                    : 'border border-[var(--tc-border)] bg-white/5 text-[var(--tc-muted)]'
              }`}
            >
              {i < current ? '\u2713' : i + 1}
            </div>
            <span className={`mt-1.5 text-[10px] font-medium ${i <= current ? 'text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>
              {label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div className={`mx-1.5 mb-5 h-px w-8 sm:w-12 transition-colors duration-300 ${i < current ? 'bg-[var(--tc-success)]' : 'bg-[var(--tc-border)]'}`} />
          )}
        </div>
      ))}
    </div>
  )
}

function CheckoutContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialPlan = searchParams.get('plan') === 'annual' ? 'annual' : 'monthly'

  const [step, setStep] = useState(0)
  const [plan, setPlan] = useState<'monthly' | 'annual'>(initialPlan as 'monthly' | 'annual')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [verifyCode, setVerifyCode] = useState('')
  const [workspaceName, setWorkspaceName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const price = plan === 'annual' ? annualPrice : monthlyPrice
  const interval = plan === 'annual' ? '/year' : '/month'
  const savings = monthlyPrice * 12 - annualPrice

  /* ── Step 1 → Step 2 ── */
  const goToAccount = () => {
    setError('')
    setStep(1)
  }

  /* ── Step 2: Register ── */
  const registerAccount = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
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
      setStep(2)
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  /* ── Step 3: Verify code ── */
  const submitCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/verify-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code: verifyCode }),
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Verification failed')
        return
      }
      setWorkspaceName(`${displayName || email.split('@')[0]}'s Workspace`)
      setStep(3)
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  /* ── Step 4: Create workspace & redirect to payment ── */
  const createWorkspace = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const loginRes = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
      })
      const loginData = await loginRes.json().catch(() => ({}))
      if (!loginRes.ok) {
        setError(loginData.detail || 'Sign-in failed')
        return
      }

      if (loginData.needs_onboarding) {
        const wsRes = await fetch('/api/workspaces', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: workspaceName.trim() || 'My Workspace' }),
          credentials: 'include',
        })
        if (!wsRes.ok) {
          const wsData = await wsRes.json().catch(() => ({}))
          setError(wsData.detail || 'Failed to create workspace')
          return
        }
      }

      const checkoutRes = await fetch('/api/billing/create-checkout-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval: plan }),
        credentials: 'include',
      })
      const checkoutData = await checkoutRes.json().catch(() => ({}))
      if (!checkoutRes.ok) {
        if (checkoutRes.status === 503) {
          router.push('/dashboard')
          return
        }
        setError(checkoutData.detail || 'Failed to start checkout')
        return
      }
      if (checkoutData.checkout_url) {
        window.location.href = checkoutData.checkout_url
      }
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen">
      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-[var(--tc-border)]" style={{ background: 'rgba(8,17,31,0.82)', backdropFilter: 'blur(16px)' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
          <Link href="/" className="flex items-center gap-2.5 font-bold text-[var(--tc-text)]">
            <div className="grid h-8 w-8 place-items-center rounded-lg text-base" style={{ background: 'linear-gradient(135deg,#7c96ff,#5b7cff 55%,#2dd4bf)', boxShadow: '0 8px 20px rgba(91,124,255,0.3)' }}>&#10003;</div>
            <span className="text-[15px]">Trust Copilot</span>
          </Link>
          <Link href="/login" className="text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Sign In</Link>
        </div>
      </nav>

      <div className="relative overflow-hidden pb-2 pt-12 sm:pt-16">
        <div className="pointer-events-none absolute inset-0" style={{ background: 'radial-gradient(ellipse 60% 50% at 50% 0%, rgba(91,124,255,0.10), transparent)' }} />
      </div>

      <div className="relative mx-auto max-w-lg px-5 pb-20">
        <StepIndicator current={step} />

        {/* ════════ Step 1: Plan + Payment Method ════════ */}
        {step === 0 && (
          <div className="animate-[fadeIn_0.3s_ease-out]">
            <h2 className="mb-2 text-center text-xl font-bold text-[var(--tc-text)]">Choose your plan</h2>
            <p className="mb-6 text-center text-sm text-[var(--tc-muted)]">One plan, everything included. Pick your billing cycle.</p>

            {/* Plan cards */}
            <div className="space-y-3">
              <button
                onClick={() => setPlan('monthly')}
                className={`w-full rounded-2xl border p-5 text-left transition-all duration-200 ${
                  plan === 'monthly'
                    ? 'border-[var(--tc-primary)] bg-[rgba(91,124,255,0.08)] shadow-[0_0_24px_rgba(91,124,255,0.12)]'
                    : 'border-[var(--tc-border)] bg-[var(--tc-panel)] hover:border-[var(--tc-muted)]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[var(--tc-text)]">Monthly</div>
                    <div className="mt-0.5 text-xs text-[var(--tc-muted)]">Billed monthly. Cancel anytime.</div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-extrabold text-[var(--tc-text)]"><span className="line-through opacity-40">${monthlyPrice}</span> <span className="text-[var(--tc-success)]">FREE</span></div>
                    <div className="text-xs text-[var(--tc-muted)]">/month</div>
                    <div className="mt-1 text-[10px] font-medium text-[var(--tc-success)]">until April 5, 2026</div>
                  </div>
                </div>
              </button>

              <button
                onClick={() => setPlan('annual')}
                className={`relative w-full rounded-2xl border p-5 text-left transition-all duration-200 ${
                  plan === 'annual'
                    ? 'border-[var(--tc-primary)] bg-[rgba(91,124,255,0.08)] shadow-[0_0_24px_rgba(91,124,255,0.12)]'
                    : 'border-[var(--tc-border)] bg-[var(--tc-panel)] hover:border-[var(--tc-muted)]'
                }`}
              >
                <span className="absolute -top-2.5 right-4 rounded-full bg-[rgba(34,197,94,0.15)] border border-[rgba(34,197,94,0.25)] px-2.5 py-0.5 text-[10px] font-semibold text-[var(--tc-success)]">
                  Save ${savings}/year
                </span>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-[var(--tc-text)]">Annual</div>
                    <div className="mt-0.5 text-xs text-[var(--tc-muted)]">Billed annually. Cancel anytime.</div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-extrabold text-[var(--tc-text)]"><span className="line-through opacity-40">${annualPrice}</span> <span className="text-[var(--tc-success)]">FREE</span></div>
                    <div className="text-xs text-[var(--tc-muted)]">/year</div>
                    <div className="mt-1 text-[10px] font-medium text-[var(--tc-success)]">until April 5, 2026</div>
                  </div>
                </div>
              </button>
            </div>

            {/* Features list */}
            <div className="mt-6 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] p-5">
              <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--tc-primary-2)]">Everything included</h3>
              <ul className="space-y-2">
                <CheckItem>Unlimited questionnaire uploads</CheckItem>
                <CheckItem>Evidence-grounded AI answers</CheckItem>
                <CheckItem>Compliance gap detection &amp; analytics</CheckItem>
                <CheckItem>Review, approval, and export workflow</CheckItem>
                <CheckItem>Public Trust Center portal</CheckItem>
                <CheckItem>Vendor request management</CheckItem>
                <CheckItem>Gmail &amp; Slack evidence ingestion</CheckItem>
                <CheckItem>Workspace with team collaboration</CheckItem>
              </ul>
            </div>

            <button
              onClick={goToAccount}
              className="tc-btn-primary mt-6 flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90"
            >
              Continue &mdash; Free until April 5
            </button>
            <p className="mt-3 text-center text-[10px] text-[var(--tc-muted)]">No credit card required now. Card will be requested after April 5.</p>
          </div>
        )}

        {/* ════════ Step 2: Create Account ════════ */}
        {step === 1 && (
          <div className="animate-[fadeIn_0.3s_ease-out]">
            <h2 className="mb-2 text-center text-xl font-bold text-[var(--tc-text)]">Create your account</h2>
            <p className="mb-6 text-center text-sm text-[var(--tc-muted)]">
              We&apos;ll send a 6-digit verification code to your email.
            </p>

            <div className="mb-5 flex items-center justify-center gap-2 rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-4 py-2.5 text-xs text-[var(--tc-muted)]">
              <span>{plan === 'annual' ? 'Annual' : 'Monthly'} &middot; <span className="font-semibold text-[var(--tc-success)]">FREE until April 5</span></span>
              <button onClick={() => setStep(0)} className="ml-1 text-[var(--tc-primary-2)] underline">Change</button>
            </div>

            <form onSubmit={registerAccount} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--tc-text)]">Email</label>
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-2.5 text-sm text-[var(--tc-text)] outline-none transition focus:border-[var(--tc-primary)] focus:ring-1 focus:ring-[var(--tc-primary)]"
                  placeholder="you@company.com"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--tc-text)]">Display name <span className="text-[var(--tc-muted)] font-normal">(optional)</span></label>
                <input
                  type="text"
                  autoComplete="name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-2.5 text-sm text-[var(--tc-text)] outline-none transition focus:border-[var(--tc-primary)] focus:ring-1 focus:ring-[var(--tc-primary)]"
                  placeholder="John Reinhart"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--tc-text)]">Password</label>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-2.5 text-sm text-[var(--tc-text)] outline-none transition focus:border-[var(--tc-primary)] focus:ring-1 focus:ring-[var(--tc-primary)]"
                  placeholder="Min 6 characters"
                />
              </div>

              {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="tc-btn-primary flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50"
              >
                {loading ? 'Creating account\u2026' : 'Create account & send code'}
              </button>
            </form>

            <button onClick={() => setStep(0)} className="mt-4 w-full text-center text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">
              &larr; Back
            </button>
          </div>
        )}

        {/* ════════ Step 3: Verify Code ════════ */}
        {step === 2 && (
          <div className="animate-[fadeIn_0.3s_ease-out]">
            <h2 className="mb-2 text-center text-xl font-bold text-[var(--tc-text)]">Enter verification code</h2>
            <p className="mb-6 text-center text-sm text-[var(--tc-muted)]">
              We sent a 6-digit code to <span className="font-medium text-[var(--tc-text)]">{email}</span>
            </p>

            <form onSubmit={submitCode} className="space-y-4">
              <div>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  required
                  className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-4 text-center text-2xl font-bold tracking-[0.3em] text-[var(--tc-text)] outline-none transition focus:border-[var(--tc-primary)] focus:ring-1 focus:ring-[var(--tc-primary)]"
                  placeholder="000000"
                />
              </div>

              {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}

              <button
                type="submit"
                disabled={loading || verifyCode.length < 6}
                className="tc-btn-primary flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50"
              >
                {loading ? 'Verifying\u2026' : 'Verify'}
              </button>
            </form>

            <p className="mt-4 text-center text-xs text-[var(--tc-muted)]">
              Didn&apos;t receive a code? Check your spam folder or{' '}
              <button onClick={() => setStep(1)} className="text-[var(--tc-primary-2)] underline">try again</button>.
            </p>
          </div>
        )}

        {/* ════════ Step 4: Create Workspace ════════ */}
        {step === 3 && (
          <div className="animate-[fadeIn_0.3s_ease-out]">
            <div className="mb-6 text-center">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-[rgba(34,197,94,0.12)]">
                <svg className="h-6 w-6 text-[var(--tc-success)]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M9 12l2 2 4-4" /><circle cx="12" cy="12" r="10" /></svg>
              </div>
              <h2 className="text-xl font-bold text-[var(--tc-text)]">Email verified!</h2>
              <p className="mt-1 text-sm text-[var(--tc-muted)]">Name your workspace, then add a payment method.</p>
            </div>

            <form onSubmit={createWorkspace} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-sm font-medium text-[var(--tc-text)]">Workspace name</label>
                <input
                  type="text"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  required
                  className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-2.5 text-sm text-[var(--tc-text)] outline-none transition focus:border-[var(--tc-primary)] focus:ring-1 focus:ring-[var(--tc-primary)]"
                  placeholder="Acme Corp"
                />
                <p className="mt-1.5 text-xs text-[var(--tc-muted)]">You can change this later in settings.</p>
              </div>

              <div className="rounded-xl border border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.04)] px-4 py-3">
                <div className="flex items-center gap-2 text-xs text-[var(--tc-muted)]">
                  <svg className="h-3.5 w-3.5 text-[var(--tc-success)]" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
                  <span>You&apos;ll be redirected to Stripe to add your card. <span className="font-medium text-[var(--tc-success)]">No charge until April 5, 2026.</span></span>
                </div>
              </div>

              {error && <p className="text-sm text-[var(--tc-danger)]">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="tc-btn-primary flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90 disabled:opacity-50"
              >
                {loading ? 'Setting up\u2026' : 'Create workspace & add payment method'}
              </button>
            </form>
          </div>
        )}
      </div>

      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}

export default function CheckoutPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center p-4"><p className="text-[var(--tc-muted)]">Loading&hellip;</p></main>}>
      <CheckoutContent />
    </Suspense>
  )
}
