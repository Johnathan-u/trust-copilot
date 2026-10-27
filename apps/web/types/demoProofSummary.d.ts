declare module '@/lib/demoProofSummary.mjs' {
  export const PROOF_SUMMARY_SCHEMA_VERSION: string

  export type PresentedMetric = {
    name: string
    value: number | null
    displayValue: string
    origin: string | null
    basis: string | null
    state: string | null
    unit: string | null
    commercialTraction: false
    tractionLabel: string
    windowStart: string | null
    windowEnd: string | null
    timezone: string | null
  }

  export type PresentedDemoProof = {
    schemaVersion: string | null
    summaryId: number | null
    contentHash: string | null
    status: string | null
    state: string | null
    reason: string | null
    commercialTraction: false
    tractionLabel: string
    dataWindow: Record<string, unknown> | null
    rows: PresentedMetric[]
    synthetic: Array<Record<string, unknown>>
    unsupported: Array<Record<string, unknown>>
    partialFailures: Array<Record<string, unknown>>
  }

  export function presentDemoProof(payload: unknown): PresentedDemoProof
}
