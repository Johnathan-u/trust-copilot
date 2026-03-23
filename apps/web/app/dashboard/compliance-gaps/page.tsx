'use client'

import { useCallback, useEffect, useState } from 'react'
import { Card } from '@/components/ui'
import { ListSkeleton } from '@/components/ui/Skeleton'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  CartesianGrid,
  Legend,
} from 'recharts'

type KPI = {
  total_questions: number
  total_answered: number
  total_drafted: number
  total_insufficient: number
  coverage_pct: number
  high_confidence_pct: number
  insufficient_pct: number
  blind_spot_count: number
}

type FrameworkCoverage = {
  framework: string
  total: number
  drafted: number
  insufficient: number
  coverage_pct: number
}

type BlindSpot = { subject: string; insufficient_count: number; total: number }
type WeakArea = { subject: string; avg_confidence: number; count: number }
type EvidenceStrength = { subject: string; avg_evidence_count: number; total_answers: number }
type RecommendedEvidence = { title: string; improves_questions: number }
type TrendPoint = { date: string; coverage_pct: number; insufficient_pct: number; low_confidence_pct: number }
type DrillRow = {
  subject: string
  framework: string
  questions_seen: number
  answered: number
  low_confidence: number
  insufficient: number
}

type CoverageData = {
  kpi: KPI
  framework_coverage: FrameworkCoverage[]
  blind_spots: BlindSpot[]
  weak_areas: WeakArea[]
  evidence_strength: EvidenceStrength[]
  recommended_evidence: RecommendedEvidence[]
  trends: TrendPoint[]
  drill_down: DrillRow[]
}

const BLUES = ['#5b7cff', '#7c93ff', '#3b5bdb', '#4263eb', '#5c7cfa', '#748ffc']
const WARM = ['#f59e0b', '#ef4444', '#f97316', '#ec4899', '#e11d48', '#d97706', '#dc2626', '#ea580c', '#db2777', '#be123c']
const TEAL = ['#10b981', '#06b6d4', '#14b8a6', '#0ea5e9', '#059669', '#0891b2']

function KPICard({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  return (
    <Card className="flex-1 min-w-[160px] p-4">
      <p className="text-xs font-medium text-[var(--tc-muted)] uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold mt-1" style={{ color }}>{value}</p>
      {sub && <p className="text-[11px] text-[var(--tc-muted)] mt-0.5">{sub}</p>}
    </Card>
  )
}

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-semibold text-[var(--tc-text)]">{title}</h2>
      {sub && <p className="text-xs text-[var(--tc-muted)] mt-0.5">{sub}</p>}
    </div>
  )
}

function HBar({ data, dataKey, nameKey, colors, height }: {
  data: Record<string, unknown>[]
  dataKey: string
  nameKey: string
  colors: string[]
  height?: number
}) {
  const h = height ?? Math.max(180, data.length * 36 + 40)
  return (
    <div style={{ width: '100%', height: h }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 140, right: 24, top: 4, bottom: 4 }}>
          <XAxis type="number" allowDecimals={false} tick={{ fill: 'var(--tc-muted)', fontSize: 11 }} />
          <YAxis
            type="category"
            dataKey={nameKey}
            width={130}
            tick={{ fill: 'var(--tc-text)', fontSize: 11 }}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ background: 'var(--tc-panel)', border: '1px solid var(--tc-border)', borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: 'var(--tc-text)', fontWeight: 600 }}
            itemStyle={{ color: 'var(--tc-muted)' }}
          />
          <Bar dataKey={dataKey} radius={[0, 4, 4, 0]} barSize={18}>
            {data.map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function ComplianceCoveragePage() {
  const [data, setData] = useState<CoverageData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showDrillDown, setShowDrillDown] = useState(false)

  const fetchData = useCallback(() => {
    fetch('/api/compliance-coverage', { credentials: 'include' })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json()
      })
      .then((d) => setData(d as CoverageData))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { setLoading(true); fetchData() }, [fetchData])

  useEffect(() => {
    const id = setInterval(fetchData, 60_000)
    return () => clearInterval(id)
  }, [fetchData])

  if (loading) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Compliance Coverage</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">See where your evidence is strong, weak, and missing.</p>
        </div>
        <Card className="p-6"><ListSkeleton rows={8} /></Card>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="min-w-0 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-[var(--tc-text)]">Compliance Coverage</h1>
          <p className="mt-1 text-sm text-[var(--tc-muted)]">See where your evidence is strong, weak, and missing.</p>
        </div>
        <Card className="p-6">
          <p className="text-[var(--tc-muted)]">
            {data?.kpi?.total_questions === 0
              ? 'No questionnaire data yet. Upload a questionnaire and generate answers to see coverage.'
              : `Unable to load coverage data. ${error ?? ''}`}
          </p>
        </Card>
      </div>
    )
  }

  const { kpi, framework_coverage, blind_spots, weak_areas, evidence_strength, recommended_evidence, trends, drill_down } = data

  const isEmpty = kpi.total_questions === 0

  return (
    <div className="min-w-0 space-y-6 pb-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Compliance Coverage</h1>
        <p className="mt-1 text-sm text-[var(--tc-muted)]">See where your evidence is strong, weak, and missing.</p>
      </div>

      {isEmpty ? (
        <Card className="p-6">
          <p className="text-[var(--tc-muted)]">No questionnaire data yet. Upload a questionnaire and generate answers to see your compliance coverage.</p>
        </Card>
      ) : (
        <>
          {/* SECTION 1 — KPI Cards */}
          <div className="flex flex-wrap gap-3">
            <KPICard
              label="Coverage"
              value={`${kpi.coverage_pct}%`}
              sub={`${kpi.total_drafted} of ${kpi.total_questions} questions answered`}
              color="#10b981"
            />
            <KPICard
              label="High Confidence"
              value={`${kpi.high_confidence_pct}%`}
              sub="of drafted answers"
              color="#5b7cff"
            />
            <KPICard
              label="Insufficient"
              value={`${kpi.insufficient_pct}%`}
              sub={`${kpi.total_insufficient} questions lack evidence`}
              color={kpi.insufficient_pct > 20 ? '#ef4444' : '#f59e0b'}
            />
            <KPICard
              label="Blind Spots"
              value={String(kpi.blind_spot_count)}
              sub="subject areas with gaps"
              color={kpi.blind_spot_count > 3 ? '#ef4444' : '#f59e0b'}
            />
          </div>

          {/* SECTION 2 — Framework Coverage */}
          {framework_coverage.length > 0 && (
            <Card className="p-5">
              <SectionHeader
                title="Framework Coverage"
                sub="Answer coverage by detected framework"
              />
              <HBar
                data={framework_coverage.map((f) => ({ ...f, name: f.framework, value: f.coverage_pct }))}
                dataKey="coverage_pct"
                nameKey="name"
                colors={BLUES}
              />
              <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-[var(--tc-muted)] px-1">
                {framework_coverage.map((f) => (
                  <span key={f.framework}>
                    {f.framework}: <span className="text-[var(--tc-text)] font-medium">{f.drafted}</span>/{f.total} drafted
                    {f.insufficient > 0 && <span className="text-amber-400 ml-1">({f.insufficient} insufficient)</span>}
                  </span>
                ))}
              </div>
            </Card>
          )}

          {/* SECTION 3 — Blind Spots */}
          {blind_spots.length > 0 && (
            <Card className="p-5">
              <SectionHeader
                title="Top Blind Spots"
                sub="Subject areas with the most insufficient or missing answers"
              />
              <HBar
                data={blind_spots.map((b) => ({ ...b, name: b.subject, value: b.insufficient_count }))}
                dataKey="insufficient_count"
                nameKey="name"
                colors={WARM}
              />
            </Card>
          )}

          {/* SECTION 4 — Weak Areas */}
          {weak_areas.length > 0 && (
            <Card className="p-5">
              <SectionHeader
                title="Weak Areas"
                sub="Subject areas where answers exist but confidence is low (below 60%)"
              />
              <HBar
                data={weak_areas.map((w) => ({ ...w, name: w.subject, value: w.avg_confidence }))}
                dataKey="avg_confidence"
                nameKey="name"
                colors={WARM}
              />
            </Card>
          )}

          {/* SECTION 5 — Evidence Strength */}
          {evidence_strength.length > 0 && (
            <Card className="p-5">
              <SectionHeader
                title="Evidence Strength"
                sub="Average number of supporting citations per answer, by subject"
              />
              <HBar
                data={evidence_strength.map((e) => ({ ...e, name: e.subject, value: e.avg_evidence_count }))}
                dataKey="avg_evidence_count"
                nameKey="name"
                colors={TEAL}
              />
            </Card>
          )}

          {/* SECTION 6 — Recommended Evidence */}
          {recommended_evidence.length > 0 && (
            <Card className="p-5">
              <SectionHeader
                title="Recommended Next Evidence"
                sub="Upload these documents to close the most gaps"
              />
              <div className="space-y-2">
                {recommended_evidence.map((r, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-lg border border-[var(--tc-border)] px-4 py-3 hover:bg-white/[0.02] transition"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-lg">📄</span>
                      <span className="text-sm text-[var(--tc-text)] font-medium">{r.title}</span>
                    </div>
                    <span className="text-xs text-[var(--tc-muted)] whitespace-nowrap">
                      improves <span className="text-[var(--tc-text)] font-semibold">{r.improves_questions}</span> questions
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* SECTION 7 — Trends */}
          {trends.length > 1 && (
            <Card className="p-5">
              <SectionHeader
                title="Coverage Trends"
                sub="How coverage, insufficients, and low-confidence answers have changed over time"
              />
              <div style={{ width: '100%', height: 260 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trends} margin={{ left: 8, right: 16, top: 8, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: 'var(--tc-muted)', fontSize: 10 }}
                      tickFormatter={(v: string) => v.slice(5)}
                    />
                    <YAxis
                      tick={{ fill: 'var(--tc-muted)', fontSize: 10 }}
                      domain={[0, 100]}
                      tickFormatter={(v: number) => `${v}%`}
                    />
                    <Tooltip
                      contentStyle={{ background: 'var(--tc-panel)', border: '1px solid var(--tc-border)', borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ color: 'var(--tc-text)', fontWeight: 600 }}
                      formatter={(v: number) => [`${v}%`]}
                    />
                    <Legend wrapperStyle={{ fontSize: 11, color: 'var(--tc-muted)' }} />
                    <Line type="monotone" dataKey="coverage_pct" name="Coverage %" stroke="#10b981" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="insufficient_pct" name="Insufficient %" stroke="#ef4444" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="low_confidence_pct" name="Low Confidence %" stroke="#f59e0b" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}

          {/* SECTION 8 — Drill-Down Table */}
          {drill_down.length > 0 && (
            <Card className="p-5">
              <div className="flex items-center justify-between mb-3">
                <SectionHeader
                  title="Coverage Detail"
                  sub="Subject × framework breakdown"
                />
                <button
                  onClick={() => setShowDrillDown(!showDrillDown)}
                  className="text-xs text-[var(--tc-primary)] hover:underline"
                >
                  {showDrillDown ? 'Hide table' : 'Show table'}
                </button>
              </div>
              {showDrillDown && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[var(--tc-border)] text-[var(--tc-muted)]">
                        <th className="text-left py-2 pr-4 font-medium">Subject</th>
                        <th className="text-left py-2 pr-4 font-medium">Framework</th>
                        <th className="text-right py-2 pr-4 font-medium">Seen</th>
                        <th className="text-right py-2 pr-4 font-medium">Answered</th>
                        <th className="text-right py-2 pr-4 font-medium">Low Conf.</th>
                        <th className="text-right py-2 font-medium">Insufficient</th>
                      </tr>
                    </thead>
                    <tbody>
                      {drill_down.map((row, i) => (
                        <tr key={i} className="border-b border-[var(--tc-border)] border-opacity-30 hover:bg-white/[0.02]">
                          <td className="py-2 pr-4 text-[var(--tc-text)]">{row.subject}</td>
                          <td className="py-2 pr-4 text-[var(--tc-muted)]">{row.framework}</td>
                          <td className="py-2 pr-4 text-right text-[var(--tc-text)]">{row.questions_seen}</td>
                          <td className="py-2 pr-4 text-right text-[var(--tc-text)]">{row.answered}</td>
                          <td className="py-2 pr-4 text-right">
                            <span className={row.low_confidence > 0 ? 'text-amber-400' : 'text-[var(--tc-muted)]'}>
                              {row.low_confidence}
                            </span>
                          </td>
                          <td className="py-2 text-right">
                            <span className={row.insufficient > 0 ? 'text-red-400' : 'text-[var(--tc-muted)]'}>
                              {row.insufficient}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
