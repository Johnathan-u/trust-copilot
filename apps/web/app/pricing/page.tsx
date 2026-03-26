'use client'

import { useState } from 'react'
import Link from 'next/link'

function CheckItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-sm text-[var(--tc-muted)]">
      <span className="mt-0.5 text-[var(--tc-success)]">✓</span>
      <span>{children}</span>
    </li>
  )
}

function FaqItem({ q, a }: { q: string; a: string }) {
  return (
    <div className="border-b border-[var(--tc-border)] py-5 last:border-0">
      <h3 className="text-sm font-semibold text-[var(--tc-text)]">{q}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-[var(--tc-muted)]">{a}</p>
    </div>
  )
}

export default function PricingPage() {
  const [annual, setAnnual] = useState(false)
  const monthlyPrice = 25
  const annualPrice = 250
  const displayPrice = annual ? annualPrice : monthlyPrice
  const interval = annual ? '/year' : '/month'
  const savings = annual ? `Save $${monthlyPrice * 12 - annualPrice}/year` : null

  return (
    <div className="relative min-h-screen">
      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b border-[var(--tc-border)]" style={{ background: 'rgba(8,17,31,0.82)', backdropFilter: 'blur(16px)' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
          <Link href="/" className="flex items-center gap-2.5 font-bold text-[var(--tc-text)]">
            <div className="grid h-8 w-8 place-items-center rounded-lg text-base" style={{ background: 'linear-gradient(135deg,#7c96ff,#5b7cff 55%,#2dd4bf)', boxShadow: '0 8px 20px rgba(91,124,255,0.3)' }}>✓</div>
            <span className="text-[15px]">Trust Copilot</span>
          </Link>
          <div className="flex items-center gap-3">
            <Link href="/login" className="text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Sign In</Link>
            <Link href="/checkout" className="tc-btn-primary rounded-lg px-4 py-1.5 text-sm transition hover:opacity-90">Get Started</Link>
          </div>
        </div>
      </nav>

      {/* Header */}
      <div className="relative overflow-hidden pb-4 pt-16 sm:pt-24">
        <div className="pointer-events-none absolute inset-0" style={{ background: 'radial-gradient(ellipse 60% 50% at 50% 0%, rgba(91,124,255,0.14), transparent)' }} />
        <div className="relative mx-auto max-w-3xl px-5 text-center">
          <h1 className="text-3xl font-extrabold tracking-tight text-[var(--tc-text)] sm:text-4xl">Simple, transparent pricing</h1>
          <p className="mt-3 text-base text-[var(--tc-muted)]">One plan. Everything included. No per-seat charges.</p>
        </div>
      </div>

      {/* Billing toggle */}
      <div className="mx-auto flex max-w-md items-center justify-center gap-4 px-5 pt-8">
        <span className={`text-sm transition-colors duration-200 ${!annual ? 'font-semibold text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>Monthly</span>
        <button
          role="switch"
          aria-checked={annual}
          onClick={() => setAnnual(!annual)}
          className={`relative h-7 w-[52px] shrink-0 rounded-full border transition-colors duration-300 ease-in-out ${annual ? 'border-[rgba(91,124,255,0.4)] bg-[rgba(91,124,255,0.25)]' : 'border-[var(--tc-border)] bg-white/5'}`}
        >
          <span
            className={`absolute top-[3px] left-[3px] h-[20px] w-[20px] rounded-full shadow-md transition-all duration-300 ease-in-out ${annual ? 'translate-x-[24px] bg-[var(--tc-primary)]' : 'translate-x-0 bg-[var(--tc-muted)]'}`}
          />
        </button>
        <span className={`text-sm transition-colors duration-200 ${annual ? 'font-semibold text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>Annual</span>
        <span
          className={`ml-1 rounded-full bg-[rgba(34,197,94,0.12)] border border-[rgba(34,197,94,0.18)] px-2.5 py-0.5 text-xs font-medium text-[var(--tc-success)] transition-all duration-500 ease-out ${annual ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-1 pointer-events-none'}`}
        >
          Save ${monthlyPrice * 12 - annualPrice}/year
        </span>
      </div>

      {/* Plan card */}
      <div className="mx-auto max-w-md px-5 py-8">
        <div className="rounded-2xl border border-[rgba(91,124,255,0.25)] bg-[var(--tc-panel)] p-8 shadow-[0_0_60px_rgba(91,124,255,0.06)]">
          <div className="mb-2 text-center">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--tc-primary-2)]">Pro Plan</span>
          </div>
          <div className="mb-6 text-center">
            <div className="text-5xl font-extrabold text-[var(--tc-text)]"><span className="line-through opacity-40">${displayPrice}</span> <span className="text-[var(--tc-success)]">FREE</span><span className="text-lg font-medium text-[var(--tc-muted)]">{interval}</span></div>
            <p className="mt-1 text-sm font-medium text-[var(--tc-success)]">Free until April 5, 2026</p>
            <p className="mt-0.5 text-xs text-[var(--tc-muted)]">{annual ? 'Then billed annually. Cancel anytime.' : 'Then billed monthly. Cancel anytime.'}</p>
          </div>

          <ul className="mb-8 space-y-3">
            <CheckItem>Unlimited questionnaire uploads</CheckItem>
            <CheckItem>Evidence-grounded AI answers</CheckItem>
            <CheckItem>Compliance gap detection and analytics</CheckItem>
            <CheckItem>Full review, approval, and export workflow</CheckItem>
            <CheckItem>Public Trust Center portal</CheckItem>
            <CheckItem>Vendor request management with secure links</CheckItem>
            <CheckItem>Gmail and Slack evidence ingestion</CheckItem>
            <CheckItem>Workspace with team collaboration</CheckItem>
            <CheckItem>Role-based access and audit logging</CheckItem>
            <CheckItem>AI model and response style controls</CheckItem>
          </ul>

          <Link href={`/checkout?plan=${annual ? 'annual' : 'monthly'}`} className="tc-btn-primary flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90">
            Get Started
          </Link>
          <p className="mt-3 text-center text-xs text-[var(--tc-muted)]">
            Want to explore first? <Link href="/login?demo=true" className="text-[var(--tc-soft)] underline">Try the demo</Link>
          </p>
        </div>
      </div>

      {/* FAQ */}
      <div className="mx-auto max-w-2xl px-5 py-12">
        <h2 className="mb-6 text-center text-xl font-bold text-[var(--tc-text)]">Frequently asked questions</h2>
        <div className="rounded-2xl border border-[var(--tc-border)] bg-[var(--tc-panel)] px-6">
          <FaqItem q="What questionnaire formats are supported?" a="Trust Copilot parses Excel, CSV, and common security questionnaire formats automatically. Upload the file and questions are extracted and classified." />
          <FaqItem q="How are answers generated?" a="Answers are generated by AI using retrieval-augmented generation (RAG). Every answer is grounded in your actual uploaded evidence documents — not generic text or hallucinations." />
          <FaqItem q="Can I collaborate with my team?" a="Yes. Each workspace supports multiple members with role-based access controls. Admins can manage members, roles, and notification preferences." />
          <FaqItem q="What happens to my data?" a="Your documents stay in your workspace and are never used to train AI models. Data is isolated per workspace with strict access controls." />
          <FaqItem q="Can I cancel anytime?" a="Yes. There are no contracts or commitments. Cancel your subscription at any time and retain access through the end of your billing period." />
          <FaqItem q="Is there a free trial?" a="You can explore the full product with our demo workspace before signing up. Click 'Try Demo' to see Trust Copilot in action with sample data." />
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-[var(--tc-border)] py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-5 sm:flex-row sm:justify-between">
          <div className="flex items-center gap-2 text-sm text-[var(--tc-muted)]">
            <div className="grid h-6 w-6 place-items-center rounded-md text-xs" style={{ background: 'linear-gradient(135deg,#7c96ff,#5b7cff 55%,#2dd4bf)' }}>✓</div>
            <span>Trust Copilot</span>
            <span className="ml-1 opacity-50">&copy; {new Date().getFullYear()}</span>
          </div>
          <div className="flex flex-wrap justify-center gap-5 text-sm text-[var(--tc-muted)]">
            <Link href="/" className="transition hover:text-[var(--tc-text)]">Home</Link>
            <Link href="/login" className="transition hover:text-[var(--tc-text)]">Sign In</Link>
            <Link href="/checkout" className="transition hover:text-[var(--tc-text)]">Sign Up</Link>
            <Link href="/trust" className="transition hover:text-[var(--tc-text)]">Trust Center</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
