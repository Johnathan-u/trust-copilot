'use client'

import { useEffect, useState } from 'react'
import {
  readCanonicalControl,
  type CanonicalControl,
} from '@/lib/controlContract'
import { failureOf, loadSection, type SectionResult } from '@/lib/section-load'
import type { ControlExplanation } from '@/lib/coverageConsumer'

export type Control = {
  id: number
  name: string | null
  framework: string | null
  category: string | null
  status: string
  owner_user_id: number | null
  owner_team: string | null
  evidence_count: number
  canonical: CanonicalControl
}
export type Member = {
  user_id: number
  display_name: string
  email: string
  suspended: boolean
}
export type EvidenceLink = {
  id: number
  verified: boolean
  stale: boolean
  expired: boolean
  evidence: { title: string; source_type: string; created_at: string | null }
}

export function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Invalid response')
  return value as Record<string, unknown>
}
export function readControl(value: unknown): Control {
  const row = record(value)
  const canonical = readCanonicalControl(row)
  if (
    !Number.isSafeInteger(row.id) ||
    Number(row.id) <= 0 ||
    !canonical ||
    (row.name !== null && typeof row.name !== 'string') ||
    (row.framework !== null && typeof row.framework !== 'string')
  )
    throw new Error('Invalid control')
  return { ...(row as unknown as Control), canonical }
}
export function readControls(value: unknown): Control[] {
  if (!Array.isArray(value)) throw new Error('Invalid controls')
  return value.map(readControl)
}
export function readMembers(value: unknown): Member[] {
  const body = record(value)
  if (!Array.isArray(body.members)) throw new Error('Invalid members')
  return body.members.map((item) => {
    const row = record(item)
    if (
      !Number.isSafeInteger(row.user_id) ||
      typeof row.display_name !== 'string' ||
      typeof row.email !== 'string'
    )
      throw new Error('Invalid member')
    return row as unknown as Member
  })
}
export function readEvidence(value: unknown): EvidenceLink[] {
  if (!Array.isArray(value)) throw new Error('Invalid evidence')
  return value.map((item) => {
    const row = record(item)
    const evidence = record(row.evidence)
    if (
      !Number.isSafeInteger(row.id) ||
      typeof row.verified !== 'boolean' ||
      typeof row.stale !== 'boolean' ||
      typeof row.expired !== 'boolean' ||
      typeof evidence.title !== 'string'
    )
      throw new Error('Invalid evidence')
    return row as unknown as EvidenceLink
  })
}

export const lifecycleLabels: Record<string, string> = {
  not_implemented: 'Not implemented',
  in_progress: 'In progress',
  implemented: 'Implemented',
  verified: 'Verified',
}
const evaluationLabels: Record<string, string> = {
  qualified: 'Qualified evidence',
  gap: 'Evidence gap',
  stale: 'Stale evidence',
  unknown: 'Unknown',
  failed: 'Check failed',
  blocked: 'Not evaluated: framework unavailable',
  disabled: 'Not evaluated: disabled',
}
export function evaluationLabel(explanation?: ControlExplanation): string {
  return explanation
    ? (evaluationLabels[explanation.state] ?? 'Unknown')
    : 'Unknown'
}
export const ruleLabels: Record<string, string> = {
  no_evidence: 'No eligible evidence is linked.',
  evidence_qualifies: 'Current, approved evidence is linked.',
  expired: 'Linked evidence has expired.',
  not_approved: 'Linked evidence needs approval.',
  deleted_document: 'A linked source was removed.',
  missing_framework: 'Framework details are unavailable.',
  framework_blocked: 'Framework content is unavailable pending licensing.',
  lifecycle_disabled: 'This control is disabled.',
  check_error: 'The evidence check could not be completed.',
}

export function useResource<T>(
  url: string | null,
  parse: (value: unknown) => T
) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<SectionResult<T> | null>(null)
  useEffect(() => {
    if (!url) return
    const controller = new AbortController()
    let active = true
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    void loadSection(
      fetch(url, { credentials: 'include', signal: controller.signal }),
      parse
    )
      .then((value) => {
        if (active) setResult(value)
      })
      .catch((error) => {
        if (active) setResult({ ok: false, failure: failureOf(error) })
      })
      .finally(() => window.clearTimeout(timeout))
    return () => {
      active = false
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [url, parse, attempt])
  return {
    result,
    reload: () => {
      setResult(null)
      setAttempt((value) => value + 1)
    },
    attempt,
  }
}

export const fieldClass =
  'min-h-11 w-full rounded-tc border border-tc-border-strong bg-tc-surface px-3 py-2 text-tc-text'
export const linkClass =
  'rounded text-tc-primary underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4'
