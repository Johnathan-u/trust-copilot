'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Toast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

type ConfDist = { high: number; medium: number; low: number; none: number }

type InsightsData = {
  performance: {
    total_questions: number
    total_answers: number
    drafted: number
    insufficient: number
    avg_confidence: number
    confidence_distribution: ConfDist
  }
  weak_subjects: { subject: string; avg_confidence: number; count: number; insufficient: number }[]
  top_insufficient_subjects: { subject: string; insufficient_count: number; total: number }[]
  mapping_quality: {
    total_signals: number
    questions_with_signals: number
    questions_without_signals: number
    by_quality: Record<string, number>
  }
  evidence_vs_confidence: { bucket: string; answer_count: number; avg_confidence: number }[]
  failure_reasons: { reason: string; label: string; count: number }[]
}

type CoverageData = {
  recommended_evidence: { title: string; improves_questions: number }[]
}

type GovSettings = Record<string, any>

const QUALITY_LABELS: Record<string, { label: string; color: string }> = {
  llm_structured:     { label: 'LLM structured',     color: 'bg-emerald-500' },
  llm_rerank:         { label: 'LLM re-ranked',      color: 'bg-blue-500' },
  heuristic_fallback: { label: 'Heuristic fallback',  color: 'bg-amber-500' },
  unknown:            { label: 'Unknown',             color: 'bg-gray-500' },
}

const FAILURE_COLORS: Record<string, string> = {
  no_evidence:                  '#ef4444',
  retrieval_noise_floor:        '#f97316',
  weak_control_path:            '#eab308',
  weak_control_path_low_tier:   '#a3e635',
  weak_retrieval_no_control:    '#22d3ee',
  weak_retrieval_low_tier_docs: '#818cf8',
  unknown:                      '#94a3b8',
}

function pct(n: number, d: number): string {
  if (d === 0) return '0'
  return Math.round((n / d) * 100).toString()
}

function prettySub(s: string): string {
  return s
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function HBar({ value, max, color }: { value: number; max: number; color: string }) {
  const w = max > 0 ? Math.max(2, (value / max) * 100) : 0
  return (
    <div className="h-3 w-full rounded-full bg-white/5 overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${w}%`, backgroundColor: color }} />
    </div>
  )
}

export default function AIInsightsPage() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const [toast, setToast] = useState<string | null>(null)

  const [insights, setInsights] = useState<InsightsData | null>(null)
  const [coverage, setCoverage] = useState<CoverageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [advOpen, setAdvOpen] = useState(false)

  const fetchInsights = useCallback(() => {
    Promise.all([
      fetch('/api/ai-insights', { credentials: 'include' }).then((r) => (r.ok ? r.json() : null)),
      fetch('/api/compliance-coverage', { credentials: 'include' }).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([ins, cov]) => {
        setInsights(ins as InsightsData | null)
        setCoverage(cov as CoverageData | null)
      })
      .catch(() => {
        setInsights(null)
        setCoverage(null)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { setLoading(true); fetchInsights() }, [fetchInsights])

  useEffect(() => {
    const id = setInterval(fetchInsights, 60_000)
    return () => clearInterval(id)
  }, [fetchInsights])

  if (!canAdmin) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">AI Insights</h1>
        <Card className="p-6 text-center text-[var(--tc-muted)]">Admin access is required to view AI performance insights.</Card>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">AI Insights</h1>
        <Card className="p-6 text-center text-[var(--tc-muted)]">Loading AI performance data...</Card>
      </div>
    )
  }

  if (!insights) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">AI Insights</h1>
        <Card className="p-6 text-center text-[var(--tc-muted)]">Unable to load AI insights. Make sure questionnaires have been processed.</Card>
      </div>
    )
  }

  const p = insights.performance
  const totalConf = p.confidence_distribution.high + p.confidence_distribution.medium + p.confidence_distribution.low + p.confidence_distribution.none
  const maxWeak = Math.max(...(insights.weak_subjects.map((s) => s.count)), 1)
  const maxInsuff = Math.max(...(insights.top_insufficient_subjects.map((s) => s.insufficient_count)), 1)
  const maxEvBucket = Math.max(...(insights.evidence_vs_confidence.map((e) => e.answer_count)), 1)
  const maxFailure = Math.max(...(insights.failure_reasons.map((f) => f.count)), 1)
  const recommendations = coverage?.recommended_evidence ?? []

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">AI Insights</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)] max-w-2xl">
          Understand how AI is performing, where it struggles, and what will improve answer quality.
        </p>
      </div>

      {/* ── Section 1: Performance Overview ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">📊</span> AI Performance Overview
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <KPICard label="Answers generated" value={p.total_answers} sub={`from ${p.total_questions} questions`} color="#3b82f6" />
          <KPICard label="High confidence" value={`${pct(p.confidence_distribution.high, totalConf)}%`} sub={`${p.confidence_distribution.high} answers >= 70`} color="#10b981" />
          <KPICard label="Medium confidence" value={`${pct(p.confidence_distribution.medium, totalConf)}%`} sub={`${p.confidence_distribution.medium} answers 40-69`} color="#eab308" />
          <KPICard label="Insufficient" value={`${pct(p.insufficient, p.total_answers)}%`} sub={`${p.insufficient} answers`} color="#ef4444" />
          <KPICard label="Avg. confidence" value={p.avg_confidence} sub="across all answers" color="#8b5cf6" />
        </div>

        {/* Confidence distribution bar */}
        <Card className="mt-3 p-4">
          <div className="text-xs font-medium text-[var(--tc-muted)] mb-2">Confidence Distribution</div>
          <div className="flex h-4 rounded-full overflow-hidden bg-white/5">
            {totalConf > 0 && (
              <>
                <div className="bg-emerald-500 transition-all" style={{ width: `${(p.confidence_distribution.high / totalConf) * 100}%` }} title={`High: ${p.confidence_distribution.high}`} />
                <div className="bg-yellow-500 transition-all" style={{ width: `${(p.confidence_distribution.medium / totalConf) * 100}%` }} title={`Medium: ${p.confidence_distribution.medium}`} />
                <div className="bg-red-500 transition-all" style={{ width: `${(p.confidence_distribution.low / totalConf) * 100}%` }} title={`Low: ${p.confidence_distribution.low}`} />
                <div className="bg-gray-600 transition-all" style={{ width: `${(p.confidence_distribution.none / totalConf) * 100}%` }} title={`No score: ${p.confidence_distribution.none}`} />
              </>
            )}
          </div>
          <div className="flex gap-4 mt-2 text-[10px] text-[var(--tc-muted)]">
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-emerald-500" /> High ({p.confidence_distribution.high})</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-yellow-500" /> Medium ({p.confidence_distribution.medium})</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-red-500" /> Low ({p.confidence_distribution.low})</span>
            <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-full bg-gray-600" /> No score ({p.confidence_distribution.none})</span>
          </div>
        </Card>
      </section>

      {/* ── Section 2: Where AI Struggles ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">⚠️</span> Where AI Struggles
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {/* Lowest confidence subjects */}
          <Card className="p-4">
            <div className="text-xs font-medium text-[var(--tc-muted)] mb-3">Lowest Confidence Subjects</div>
            {insights.weak_subjects.length === 0 ? (
              <p className="text-xs text-[var(--tc-muted)]">No weak subject areas detected.</p>
            ) : (
              <div className="space-y-2">
                {insights.weak_subjects.map((s) => (
                  <div key={s.subject}>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-[var(--tc-text)] truncate max-w-[200px]" title={prettySub(s.subject)}>{prettySub(s.subject)}</span>
                      <span className="text-[var(--tc-muted)] font-mono">{s.avg_confidence}% avg · {s.count} answers</span>
                    </div>
                    <HBar value={s.count} max={maxWeak} color="#eab308" />
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Highest insufficient rate */}
          <Card className="p-4">
            <div className="text-xs font-medium text-[var(--tc-muted)] mb-3">Highest Insufficient Rate</div>
            {insights.top_insufficient_subjects.length === 0 ? (
              <p className="text-xs text-[var(--tc-muted)]">No insufficient subjects detected.</p>
            ) : (
              <div className="space-y-2">
                {insights.top_insufficient_subjects.map((s) => (
                  <div key={s.subject}>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-[var(--tc-text)] truncate max-w-[200px]" title={prettySub(s.subject)}>{prettySub(s.subject)}</span>
                      <span className="text-[var(--tc-muted)] font-mono">{s.insufficient_count} / {s.total}</span>
                    </div>
                    <HBar value={s.insufficient_count} max={maxInsuff} color="#ef4444" />
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </section>

      {/* ── Section 3: Mapping Quality ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">🔗</span> Classification Quality
        </h2>
        <Card className="p-4">
          <div className="grid gap-3 sm:grid-cols-3 mb-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-[var(--tc-text)]">{insights.mapping_quality.questions_with_signals}</div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">Questions classified</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-amber-400">{insights.mapping_quality.questions_without_signals}</div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">Unclassified</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-[var(--tc-text)]">{insights.mapping_quality.total_signals}</div>
              <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">Total signals</div>
            </div>
          </div>

          {/* Quality breakdown */}
          <div className="text-xs font-medium text-[var(--tc-muted)] mb-2">Signal Quality Breakdown</div>
          <div className="flex h-5 rounded-full overflow-hidden bg-white/5">
            {insights.mapping_quality.total_signals > 0 && Object.entries(insights.mapping_quality.by_quality).map(([key, count]) => {
              const meta = QUALITY_LABELS[key] || QUALITY_LABELS.unknown
              return (
                <div
                  key={key}
                  className={`${meta.color} transition-all`}
                  style={{ width: `${(count / insights.mapping_quality.total_signals) * 100}%` }}
                  title={`${meta.label}: ${count}`}
                />
              )
            })}
          </div>
          <div className="flex flex-wrap gap-3 mt-2 text-[10px] text-[var(--tc-muted)]">
            {Object.entries(insights.mapping_quality.by_quality).map(([key, count]) => {
              const meta = QUALITY_LABELS[key] || QUALITY_LABELS.unknown
              return (
                <span key={key} className="flex items-center gap-1">
                  <span className={`inline-block w-2 h-2 rounded-full ${meta.color}`} />
                  {meta.label} ({count})
                </span>
              )
            })}
          </div>
        </Card>
      </section>

      {/* ── Section 4: Evidence vs AI Performance ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">📄</span> Evidence Depth vs. Confidence
        </h2>
        <Card className="p-4">
          <p className="text-xs text-[var(--tc-muted)] mb-3">Answers with more supporting evidence citations tend to have higher confidence.</p>
          <div className="space-y-3">
            {insights.evidence_vs_confidence.map((e) => (
              <div key={e.bucket}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-[var(--tc-text)] font-medium">{e.bucket}</span>
                  <span className="text-[var(--tc-muted)] font-mono">
                    {e.answer_count} answers · avg conf {e.avg_confidence}%
                  </span>
                </div>
                <div className="flex gap-2 items-center">
                  <div className="flex-1">
                    <HBar value={e.answer_count} max={maxEvBucket} color="#3b82f6" />
                  </div>
                  <div className="w-16 text-right">
                    <span className={`text-xs font-bold ${e.avg_confidence >= 70 ? 'text-emerald-400' : e.avg_confidence >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {e.avg_confidence}%
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>

      {/* ── Section 5: Why Answers Fail ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">🔍</span> Why Answers Fail
        </h2>
        <Card className="p-4">
          {insights.failure_reasons.length === 0 ? (
            <p className="text-xs text-[var(--tc-muted)]">No insufficient answers detected — all answers are performing well.</p>
          ) : (
            <>
              <p className="text-xs text-[var(--tc-muted)] mb-3">
                Breakdown of why {p.insufficient} answers were marked insufficient.
              </p>
              <div className="space-y-2">
                {insights.failure_reasons.map((f) => (
                  <div key={f.reason}>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span className="text-[var(--tc-text)]">{f.label}</span>
                      <span className="text-[var(--tc-muted)] font-mono">{f.count}</span>
                    </div>
                    <HBar value={f.count} max={maxFailure} color={FAILURE_COLORS[f.reason] || '#94a3b8'} />
                  </div>
                ))}
              </div>
              <div className="mt-4 pt-3 border-t border-white/10 text-[10px] text-[var(--tc-muted)] space-y-1">
                <div><strong className="text-[var(--tc-text)]">No evidence available</strong> — no relevant documents found for the question</div>
                <div><strong className="text-[var(--tc-text)]">Evidence too generic / noisy</strong> — retrieved documents did not meet relevance threshold</div>
                <div><strong className="text-[var(--tc-text)]">Weak control-path match</strong> — evidence was found but could not be confidently linked to the question</div>
              </div>
            </>
          )}
        </Card>
      </section>

      {/* ── Section 6: Suggested Improvements ── */}
      <section>
        <h2 className="text-sm font-semibold text-[var(--tc-text)] mb-3 flex items-center gap-2">
          <span className="text-base">💡</span> Suggested Improvements
        </h2>
        <Card className="p-4">
          {recommendations.length === 0 ? (
            <p className="text-xs text-[var(--tc-muted)]">No specific evidence recommendations available right now. Process more questionnaires to generate suggestions.</p>
          ) : (
            <>
              <p className="text-xs text-[var(--tc-muted)] mb-3">Uploading these documents would likely improve the most weak or insufficient answers.</p>
              <div className="space-y-2">
                {recommendations.map((r, i) => (
                  <div key={i} className="flex items-start gap-3 py-2 border-b border-white/5 last:border-0">
                    <span className="text-lg mt-0.5">📎</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-[var(--tc-text)]">{r.title}</div>
                      <div className="text-[10px] text-[var(--tc-muted)]">
                        Could improve <strong className="text-emerald-400">{r.improves_questions}</strong> questions
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => window.location.href = '/dashboard/documents'}
                    >
                      Upload
                    </Button>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </section>

      {/* ── Section 7: Advanced Settings (collapsed) ── */}
      <section>
        <button
          onClick={() => setAdvOpen(!advOpen)}
          className="flex items-center gap-2 text-sm font-semibold text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition-colors"
        >
          <span className="text-base">{advOpen ? '▼' : '▶'}</span>
          Advanced AI Settings
          <span className="text-[10px] font-normal ml-1">(pipeline tuning)</span>
        </button>
        {advOpen && <AdvancedSettings onToast={setToast} />}
      </section>

      {toast && <Toast title="Info" message={toast} type="success" onDismiss={() => setToast(null)} />}
    </div>
  )
}

function KPICard({ label, value, sub, color }: { label: string; value: string | number; sub: string; color: string }) {
  return (
    <Card className="p-4">
      <div className="text-[10px] uppercase tracking-wide text-[var(--tc-muted)]">{label}</div>
      <div className="mt-1 text-2xl font-bold" style={{ color }}>{value}</div>
      <div className="mt-0.5 text-[10px] text-[var(--tc-muted)]">{sub}</div>
    </Card>
  )
}

function AdvancedSettings({ onToast }: { onToast: (m: string) => void }) {
  const [settings, setSettings] = useState<GovSettings>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/ai-governance/settings', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : {}))
      .then(setSettings)
      .catch(() => setSettings({}))
      .finally(() => setLoading(false))
  }, [])

  const onSave = () => {
    setSaving(true)
    const { id, workspace_id, created_at, updated_at, ...data } = settings
    fetch('/api/ai-governance/settings', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d) { setSettings(d); onToast('Settings saved') }
      })
      .finally(() => setSaving(false))
  }

  const update = (key: string, value: any) => setSettings((s) => ({ ...s, [key]: value }))

  if (loading) return <Card className="p-4 mt-3"><p className="text-sm text-[var(--tc-muted)]">Loading...</p></Card>

  return (
    <Card className="p-4 mt-3 space-y-5">
      <p className="text-xs text-[var(--tc-muted)]">
        These settings control how AI mappings and tags affect evidence retrieval and gap analysis.
        They do not determine how draft answers are written. Most users do not need to change these.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ToggleSetting label="Require approved mappings" value={settings.require_approved_mappings} onChange={(v) => update('require_approved_mappings', v)} hint="Only approved mappings affect retrieval" />
        <ToggleSetting label="Require approved AI tags" value={settings.require_approved_ai_tags} onChange={(v) => update('require_approved_ai_tags', v)} hint="Only approved tags affect ranking" />
        <ToggleSetting label="Allow unapproved AI for retrieval" value={settings.allow_ai_unapproved_for_retrieval} onChange={(v) => update('allow_ai_unapproved_for_retrieval', v)} hint="Let unapproved AI mappings still influence search" />
        <ToggleSetting label="Allow manual overrides" value={settings.allow_manual_overrides} onChange={(v) => update('allow_manual_overrides', v)} hint="Manual mappings take priority over AI" />
      </div>

      <div className="border-t border-white/10 pt-4">
        <h4 className="text-xs font-semibold text-[var(--tc-muted)] uppercase mb-3">Confidence Thresholds</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <NumberSetting label="Min AI mapping confidence" value={settings.minimum_ai_mapping_confidence} onChange={(v) => update('minimum_ai_mapping_confidence', v)} />
          <NumberSetting label="Min AI tag confidence" value={settings.minimum_ai_tag_confidence} onChange={(v) => update('minimum_ai_tag_confidence', v)} />
        </div>
      </div>

      <div className="border-t border-white/10 pt-4">
        <h4 className="text-xs font-semibold text-[var(--tc-muted)] uppercase mb-3">Retrieval Boost Values</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <NumberSetting label="Manual mapping boost" value={settings.manual_mapping_boost} onChange={(v) => update('manual_mapping_boost', v)} />
          <NumberSetting label="Approved mapping boost" value={settings.approved_mapping_boost} onChange={(v) => update('approved_mapping_boost', v)} />
          <NumberSetting label="Approved tag boost" value={settings.approved_tag_boost} onChange={(v) => update('approved_tag_boost', v)} />
          <NumberSetting label="Control match boost" value={settings.control_match_boost} onChange={(v) => update('control_match_boost', v)} />
          <NumberSetting label="Framework tag boost" value={settings.framework_match_boost} onChange={(v) => update('framework_match_boost', v)} />
        </div>
      </div>

      <div className="pt-2">
        <Button onClick={onSave} disabled={saving}>{saving ? 'Saving...' : 'Save Settings'}</Button>
      </div>
    </Card>
  )
}

function ToggleSetting({ label, value, onChange, hint }: { label: string; value: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer group">
      <div className="relative mt-0.5">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} className="sr-only peer" />
        <div className="h-5 w-9 rounded-full bg-white/10 peer-checked:bg-[var(--tc-primary)] transition-colors" />
        <div className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white/80 transition-transform peer-checked:translate-x-4" />
      </div>
      <div>
        <span className="text-xs font-medium text-[var(--tc-text)] group-hover:text-white">{label}</span>
        {hint && <p className="text-[10px] text-[var(--tc-muted)] mt-0.5">{hint}</p>}
      </div>
    </label>
  )
}

function NumberSetting({ label, value, onChange }: { label: string; value: number | null | undefined; onChange: (v: number | null) => void }) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">{label}</label>
      <input
        type="number"
        step="0.01"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : parseFloat(e.target.value))}
        className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-[var(--tc-text)] outline-none focus:border-[var(--tc-primary)]"
      />
    </div>
  )
}
