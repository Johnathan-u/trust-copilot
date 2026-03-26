'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'

/* ───────── scroll-reveal hook ───────── */

function useReveal() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { el.classList.add('revealed'); obs.unobserve(el) } },
      { threshold: 0.15 },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return ref
}

function Section({ children, className = '', id }: { children: React.ReactNode; className?: string; id?: string }) {
  const ref = useReveal()
  return (
    <div ref={ref} id={id} className={`reveal-section ${className}`}>
      {children}
    </div>
  )
}

/* ───────── shared components ───────── */

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[rgba(91,124,255,0.25)] bg-[rgba(91,124,255,0.08)] px-3 py-1 text-xs font-medium text-[var(--tc-primary-2)]">
      {children}
    </span>
  )
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="group rounded-2xl border border-[var(--tc-border)] bg-[var(--tc-panel)] p-6 transition-all duration-300 hover:border-[rgba(91,124,255,0.3)] hover:shadow-[0_0_40px_rgba(91,124,255,0.08)]">
      <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl bg-[rgba(91,124,255,0.1)] text-xl transition-transform duration-300 group-hover:scale-110">{icon}</div>
      <h3 className="mb-2 text-[15px] font-semibold text-[var(--tc-text)]">{title}</h3>
      <p className="text-sm leading-relaxed text-[var(--tc-muted)]">{desc}</p>
    </div>
  )
}

function StepCard({ num, title, desc }: { num: string; title: string; desc: string }) {
  return (
    <div className="relative flex flex-col items-center text-center">
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-full border border-[rgba(91,124,255,0.3)] bg-[rgba(91,124,255,0.08)] text-sm font-bold text-[var(--tc-primary-2)]">{num}</div>
      <h3 className="mb-1.5 text-[15px] font-semibold text-[var(--tc-text)]">{title}</h3>
      <p className="text-sm leading-relaxed text-[var(--tc-muted)]">{desc}</p>
    </div>
  )
}

function CheckItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-sm text-[var(--tc-muted)]">
      <span className="mt-0.5 text-[var(--tc-success)]">✓</span>
      <span>{children}</span>
    </li>
  )
}

/* ───────── pricing section with toggle ───────── */

function PricingSection() {
  const ref = useReveal()
  const [annual, setAnnual] = useState(false)
  const price = annual ? 250 : 25
  const interval = annual ? '/year' : '/month'

  return (
    <div ref={ref} id="pricing" className="reveal-section mx-auto max-w-3xl px-5 py-16 sm:py-24">
      <div className="mb-6 text-center">
        <Badge>Simple pricing</Badge>
        <h2 className="mt-4 text-xl font-bold text-[var(--tc-text)] sm:text-2xl">One plan. Everything included.</h2>
        <p className="mt-2 text-sm text-[var(--tc-muted)]">No tiers, no feature gates, no per-seat pricing.</p>
      </div>

      {/* Toggle */}
      <div className="mx-auto mb-8 flex items-center justify-center gap-4">
        <span className={`text-sm transition-colors duration-200 ${!annual ? 'font-semibold text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>Monthly</span>
        <button
          role="switch"
          aria-checked={annual}
          onClick={() => setAnnual(!annual)}
          className={`relative h-7 w-[52px] shrink-0 rounded-full border transition-colors duration-300 ease-in-out ${annual ? 'border-[rgba(91,124,255,0.4)] bg-[rgba(91,124,255,0.25)]' : 'border-[var(--tc-border)] bg-white/5'}`}
        >
          <span className={`absolute top-[3px] left-[3px] h-[20px] w-[20px] rounded-full shadow-md transition-all duration-300 ease-in-out ${annual ? 'translate-x-[24px] bg-[var(--tc-primary)]' : 'translate-x-0 bg-[var(--tc-muted)]'}`} />
        </button>
        <span className={`text-sm transition-colors duration-200 ${annual ? 'font-semibold text-[var(--tc-text)]' : 'text-[var(--tc-muted)]'}`}>Annual</span>
        <span className={`ml-1 rounded-full bg-[rgba(34,197,94,0.12)] border border-[rgba(34,197,94,0.18)] px-2.5 py-0.5 text-xs font-medium text-[var(--tc-success)] transition-all duration-500 ease-out ${annual ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-1 pointer-events-none'}`}>
          Save $50/year
        </span>
      </div>

      {/* Card */}
      <div className="mx-auto max-w-md rounded-2xl border border-[rgba(91,124,255,0.25)] bg-[var(--tc-panel)] p-8">
        <div className="mb-6 text-center">
          <div className="text-4xl font-extrabold text-[var(--tc-text)]">
            <span key={price} className="inline-block animate-[fadeNum_0.3s_ease-out] line-through opacity-40">${price}</span>
            {' '}<span className="text-[var(--tc-success)]">FREE</span>
            <span className="text-lg font-medium text-[var(--tc-muted)]">{interval}</span>
          </div>
          <p className="mt-1 text-sm font-medium text-[var(--tc-success)]">Free until April 5, 2026</p>
          <p className="mt-0.5 text-xs text-[var(--tc-muted)]">{annual ? 'Then billed annually. Cancel anytime.' : 'Then billed monthly. Cancel anytime.'}</p>
        </div>
        <ul className="mb-8 space-y-3">
          <CheckItem>Unlimited questionnaire uploads</CheckItem>
          <CheckItem>Evidence-grounded AI answers</CheckItem>
          <CheckItem>Compliance gap detection and analytics</CheckItem>
          <CheckItem>Review, approval, and export workflow</CheckItem>
          <CheckItem>Public Trust Center portal</CheckItem>
          <CheckItem>Vendor request management</CheckItem>
          <CheckItem>Gmail and Slack evidence ingestion</CheckItem>
          <CheckItem>Workspace with team collaboration</CheckItem>
        </ul>
        <Link href={`/checkout?plan=${annual ? 'annual' : 'monthly'}`} className="tc-btn-primary flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition hover:opacity-90">
          Get Started
        </Link>
        <p className="mt-3 text-center text-xs text-[var(--tc-muted)]">
          Want to explore first? <Link href="/login?demo=true" className="text-[var(--tc-soft)] underline">Try the demo</Link>
        </p>
      </div>
    </div>
  )
}

/* ───────── page ───────── */

export default function HomePage() {
  return (
    <div className="relative min-h-screen">
      {/* ── Nav ── */}
      <nav className="sticky top-0 z-50 border-b border-[var(--tc-border)]" style={{ background: 'rgba(8,17,31,0.82)', backdropFilter: 'blur(16px)' }}>
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
          <Link href="/" className="flex items-center gap-2.5 font-bold text-[var(--tc-text)]">
            <div className="grid h-8 w-8 place-items-center rounded-lg text-base" style={{ background: 'linear-gradient(135deg,#7c96ff,#5b7cff 55%,#2dd4bf)', boxShadow: '0 8px 20px rgba(91,124,255,0.3)' }}>✓</div>
            <span className="text-[15px]">Trust Copilot</span>
          </Link>
          <div className="hidden items-center gap-6 sm:flex">
            <a href="#features" className="text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Features</a>
            <a href="#pricing" className="text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Pricing</a>
            <Link href="/login" className="text-sm text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Login</Link>
            <Link href="/login?demo=true" className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-3.5 py-1.5 text-sm font-medium text-[var(--tc-text)] transition hover:bg-white/10">Try Demo</Link>
            <Link href="/checkout" className="tc-btn-primary rounded-lg px-4 py-1.5 text-sm transition hover:opacity-90">Sign Up</Link>
          </div>
          {/* mobile menu */}
          <div className="flex items-center gap-2 sm:hidden">
            <Link href="/login" className="text-xs text-[var(--tc-muted)] transition hover:text-[var(--tc-text)]">Login</Link>
            <Link href="/login?demo=true" className="rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-1.5 text-xs font-medium text-[var(--tc-text)]">Demo</Link>
            <Link href="/checkout" className="tc-btn-primary rounded-lg px-3 py-1.5 text-xs">Sign Up</Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <header className="relative overflow-hidden pb-20 pt-20 sm:pt-28 lg:pt-36">
        <div className="hero-glow pointer-events-none absolute inset-0" style={{ background: 'radial-gradient(ellipse 60% 50% at 50% 0%, rgba(91,124,255,0.18), transparent)' }} />
        <div className="relative mx-auto max-w-3xl px-5 text-center">
          <div className="float-badge inline-block"><Badge>Evidence-grounded compliance AI</Badge></div>
          <h1 className="mt-6 text-3xl font-extrabold leading-tight tracking-tight text-[var(--tc-text)] sm:text-5xl lg:text-[3.4rem]">
            Compliance questionnaires,<br className="hidden sm:block" /> answered with evidence.
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-[var(--tc-muted)] sm:text-lg">
            Upload your evidence. Upload the questionnaire. Get AI-generated answers grounded in your real documents — not hallucinations.
          </p>
          <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Link href="/checkout" className="tc-btn-primary rounded-xl px-7 py-3 text-sm font-semibold transition hover:opacity-90 sm:text-base">
              Get Started — $25/mo
            </Link>
            <Link href="/login?demo=true" className="tc-btn-ghost rounded-xl px-7 py-3 text-sm font-medium transition hover:bg-white/10 sm:text-base">
              Try Demo
            </Link>
          </div>
          <p className="mt-4 text-xs text-[var(--tc-muted)]">No credit card required to explore the demo.</p>
        </div>
      </header>

      {/* ── Problem ── */}
      <Section className="mx-auto max-w-4xl px-5 py-16 text-center sm:py-24">
        <h2 className="text-xl font-bold text-[var(--tc-text)] sm:text-2xl">Compliance questionnaires take weeks.<br className="hidden sm:block" /> Generic AI makes things up.</h2>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-[var(--tc-muted)] sm:text-base">
          Security reviews, vendor assessments, and compliance questionnaires pile up. Teams copy-paste from old responses or hand them to AI that invents plausible-sounding nonsense. Trust Copilot is different — every answer is grounded in your actual evidence documents.
        </p>
      </Section>

      {/* ── How it works ── */}
      <Section className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
        <div className="mb-12 text-center">
          <Badge>How it works</Badge>
          <h2 className="mt-4 text-xl font-bold text-[var(--tc-text)] sm:text-2xl">From questionnaire to answers in minutes</h2>
        </div>
        <div className="grid gap-10 sm:grid-cols-3">
          <StepCard num="1" title="Upload evidence" desc="Upload your policies, SOC 2 reports, security docs, and compliance evidence. Trust Copilot indexes and understands them." />
          <StepCard num="2" title="Upload questionnaire" desc="Drop in the security or compliance questionnaire you need to answer. Questions are parsed and classified automatically." />
          <StepCard num="3" title="Review and export" desc="AI generates answers grounded in your evidence. Review, refine, and export — ready to send back in minutes, not weeks." />
        </div>
      </Section>

      {/* ── Features ── */}
      <Section id="features" className="mx-auto max-w-6xl px-5 py-16 sm:py-24">
        <div className="mb-12 text-center">
          <Badge>Features</Badge>
          <h2 className="mt-4 text-xl font-bold text-[var(--tc-text)] sm:text-2xl">Everything you need for compliance questionnaire automation</h2>
        </div>
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <FeatureCard icon="📄" title="Evidence-grounded answers" desc="Every AI answer cites real evidence from your uploaded documents. No hallucinations, no generic text." />
          <FeatureCard icon="📊" title="Compliance gap detection" desc="Automatically identify blind spots, weak evidence, and insufficient answers across your compliance coverage." />
          <FeatureCard icon="⚡" title="Questionnaire automation" desc="Upload a questionnaire and get AI-drafted answers in minutes. Supports common compliance frameworks." />
          <FeatureCard icon="🛡" title="Trust Center" desc="Give customers a public-facing compliance portal with your published security articles and trust documentation." />
          <FeatureCard icon="📨" title="Vendor requests" desc="Send secure questionnaire links to vendors, track response status, and manage outbound compliance requests." />
          <FeatureCard icon="🔗" title="Gmail and Slack ingestion" desc="Pull compliance evidence directly from email attachments and Slack channels into your evidence library." />
        </div>
      </Section>

      {/* ── Differentiation ── */}
      <Section className="mx-auto max-w-5xl px-5 py-16 sm:py-24">
        <div className="rounded-2xl border border-[var(--tc-border)] bg-[var(--tc-panel)] p-8 sm:p-12">
          <div className="mb-8 text-center">
            <h2 className="text-xl font-bold text-[var(--tc-text)] sm:text-2xl">Not another generic AI tool.</h2>
            <p className="mt-3 text-sm text-[var(--tc-muted)] sm:text-base">Trust Copilot is purpose-built for compliance teams.</p>
          </div>
          <div className="grid gap-8 sm:grid-cols-2">
            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Generic AI tools</h3>
              <ul className="space-y-2.5 text-sm text-[var(--tc-muted)]">
                <li className="flex items-start gap-2"><span className="mt-0.5 text-red-400">✗</span> Generate plausible text with no evidence</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-red-400">✗</span> No compliance analytics or gap detection</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-red-400">✗</span> No review, approval, or export workflow</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-red-400">✗</span> No trust portal or vendor request management</li>
              </ul>
            </div>
            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-[var(--tc-primary-2)]">Trust Copilot</h3>
              <ul className="space-y-2.5 text-sm text-[var(--tc-text)]">
                <li className="flex items-start gap-2"><span className="mt-0.5 text-[var(--tc-success)]">✓</span> Answers grounded in your uploaded evidence</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-[var(--tc-success)]">✓</span> Compliance coverage, blind spots, and weak evidence analytics</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-[var(--tc-success)]">✓</span> Full review workflow with export to Word, PDF, Excel</li>
                <li className="flex items-start gap-2"><span className="mt-0.5 text-[var(--tc-success)]">✓</span> Public trust center and secure vendor request links</li>
              </ul>
            </div>
          </div>
        </div>
      </Section>

      {/* ── Pricing ── */}
      <PricingSection />

      {/* ── Trust / reassurance ── */}
      <Section className="mx-auto max-w-4xl px-5 py-16 text-center sm:py-24">
        <h2 className="text-xl font-bold text-[var(--tc-text)] sm:text-2xl">Built for compliance teams that take security seriously.</h2>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-[var(--tc-muted)] sm:text-base">
          Your documents stay in your workspace. Evidence is never used to train models. Trust Copilot is designed to meet the security expectations of the teams that use it.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-6 text-sm text-[var(--tc-muted)]">
          <span className="flex items-center gap-2"><span className="text-[var(--tc-success)]">✓</span> Data isolation per workspace</span>
          <span className="flex items-center gap-2"><span className="text-[var(--tc-success)]">✓</span> Evidence never used for training</span>
          <span className="flex items-center gap-2"><span className="text-[var(--tc-success)]">✓</span> Role-based access controls</span>
          <span className="flex items-center gap-2"><span className="text-[var(--tc-success)]">✓</span> Audit logging</span>
        </div>
      </Section>

      {/* ── Final CTA ── */}
      <Section className="mx-auto max-w-3xl px-5 py-16 text-center sm:py-24">
        <h2 className="text-xl font-bold text-[var(--tc-text)] sm:text-2xl">Stop spending weeks on compliance questionnaires.</h2>
        <p className="mt-3 text-sm text-[var(--tc-muted)] sm:text-base">Upload your evidence. Upload the questionnaire. Get answers.</p>
        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Link href="/checkout" className="tc-btn-primary rounded-xl px-7 py-3 text-sm font-semibold transition hover:opacity-90">
            Get Started — $25/mo
          </Link>
          <Link href="/login?demo=true" className="tc-btn-ghost rounded-xl px-7 py-3 text-sm font-medium transition hover:bg-white/10">
            Try Demo
          </Link>
        </div>
      </Section>

      {/* ── Footer ── */}
      <footer className="border-t border-[var(--tc-border)] py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-5 sm:flex-row sm:justify-between">
          <div className="flex items-center gap-2 text-sm text-[var(--tc-muted)]">
            <div className="grid h-6 w-6 place-items-center rounded-md text-xs" style={{ background: 'linear-gradient(135deg,#7c96ff,#5b7cff 55%,#2dd4bf)' }}>✓</div>
            <span>Trust Copilot</span>
            <span className="ml-1 opacity-50">&copy; {new Date().getFullYear()}</span>
          </div>
          <div className="flex flex-wrap justify-center gap-5 text-sm text-[var(--tc-muted)]">
            <Link href="/login" className="transition hover:text-[var(--tc-text)]">Sign In</Link>
            <Link href="/checkout" className="transition hover:text-[var(--tc-text)]">Sign Up</Link>
            <Link href="/pricing" className="transition hover:text-[var(--tc-text)]">Pricing</Link>
            <Link href="/trust" className="transition hover:text-[var(--tc-text)]">Trust Center</Link>
          </div>
        </div>
      </footer>

      {/* ── animations CSS ── */}
      <style jsx global>{`
        .reveal-section {
          opacity: 0;
          transform: translateY(32px);
          transition: opacity 0.7s cubic-bezier(0.16, 1, 0.3, 1), transform 0.7s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .reveal-section.revealed {
          opacity: 1;
          transform: translateY(0);
        }

        @keyframes fadeNum {
          from { opacity: 0.4; transform: translateY(-6px); }
          to { opacity: 1; transform: translateY(0); }
        }

        @keyframes hero-glow {
          0%, 100% { opacity: 0.18; transform: scale(1); }
          50% { opacity: 0.28; transform: scale(1.08); }
        }
        .hero-glow {
          animation: hero-glow 6s ease-in-out infinite;
        }

        @keyframes float-badge {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
        .float-badge {
          animation: float-badge 3s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}
