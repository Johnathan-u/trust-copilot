export const FRAMEWORK_OPTIONS = [
  'SOC 2',
  'HIPAA',
  'ISO 27001',
  'NIST',
  'PCI DSS',
  'GDPR',
  'Other',
] as const

export const SUBJECT_AREA_OPTIONS = [
  'Access Control',
  'Privileged Access',
  'Incident Response',
  'Vendor Management',
  'Encryption',
  'Logging',
  'Risk Management',
  'HR / Security Training',
  'Infrastructure Security',
  'Secure SDLC',
  'Other',
] as const

export type FrameworkLabel = (typeof FRAMEWORK_OPTIONS)[number]
export type SubjectAreaLabel = (typeof SUBJECT_AREA_OPTIONS)[number]

export function normalizeLabels(values: string[] | null | undefined, fallback = 'Other'): string[] {
  const safe = Array.isArray(values) ? values : []
  const out: string[] = []
  for (const value of safe) {
    const v = `${value || ''}`.trim()
    if (v && !out.includes(v)) out.push(v)
  }
  if (out.length === 0) out.push(fallback)
  return out
}

export function formatCreatedAt(value: string | null | undefined): string {
  if (!value) return 'Created —'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return 'Created —'
  return `Created ${d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })}`
}
