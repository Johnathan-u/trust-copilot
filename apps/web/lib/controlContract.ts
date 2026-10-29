/**
 * UI consumer for the TC-21-002 canonical block on legacy and compliance controls.
 *
 * Both routes keep their existing fields. Agreement is the nested `canonical`
 * object: one id, a null version, one owner, one lifecycle, and one evidence
 * summary. A non-null version is not this contract. Framework content stays
 * unlicensed until TC-01-007.
 */

export const CONTROL_CONTRACT_VERSION = 'control-contract/v1'
export const CONTROL_EVIDENCE_CONTRACT_VERSION = 'control-evidence/v1'

export const CANONICAL_LIFECYCLES = [
  'not_implemented',
  'in_progress',
  'implemented',
  'verified',
] as const

export type CanonicalLifecycle = (typeof CANONICAL_LIFECYCLES)[number]

export type CanonicalEvidence = {
  contract_version: string
  workspace_scoped: boolean
  exactly_one_target: boolean
  legacy_count: number
  canonical_count: number
  mirrored: boolean
}

export type CanonicalControl = {
  contract_version: string
  id: string
  version: null
  content_version: null
  owner_user_id: number | null
  owner_team: string | null
  lifecycle: CanonicalLifecycle
  status_aligned: boolean
  evidence: CanonicalEvidence
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function readCanonicalControl(row: unknown): CanonicalControl | null {
  if (!isRecord(row) || !isRecord(row.canonical)) return null
  const canonical = row.canonical
  if (canonical.contract_version !== CONTROL_CONTRACT_VERSION) return null
  if (typeof canonical.id !== 'string' || canonical.id.length === 0) return null
  if (canonical.version !== null || canonical.content_version !== null)
    return null
  if (
    typeof canonical.lifecycle !== 'string' ||
    !CANONICAL_LIFECYCLES.includes(canonical.lifecycle as CanonicalLifecycle)
  ) {
    return null
  }
  if (typeof canonical.status_aligned !== 'boolean') return null
  let owner: number | null
  if (canonical.owner_user_id === null) owner = null
  else if (typeof canonical.owner_user_id === 'number')
    owner = canonical.owner_user_id
  else return null
  let team: string | null
  if (canonical.owner_team === null) team = null
  else if (typeof canonical.owner_team === 'string') team = canonical.owner_team
  else return null
  if (!isRecord(canonical.evidence)) return null
  const evidence = canonical.evidence
  if (evidence.contract_version !== CONTROL_EVIDENCE_CONTRACT_VERSION)
    return null
  if (
    evidence.workspace_scoped !== true ||
    evidence.exactly_one_target !== true
  )
    return null
  if (
    typeof evidence.legacy_count !== 'number' ||
    typeof evidence.canonical_count !== 'number' ||
    typeof evidence.mirrored !== 'boolean'
  ) {
    return null
  }
  return {
    contract_version: CONTROL_CONTRACT_VERSION,
    id: canonical.id,
    version: null,
    content_version: null,
    owner_user_id: owner,
    owner_team: team,
    lifecycle: canonical.lifecycle as CanonicalLifecycle,
    status_aligned: canonical.status_aligned,
    evidence: {
      contract_version: CONTROL_EVIDENCE_CONTRACT_VERSION,
      workspace_scoped: true,
      exactly_one_target: true,
      legacy_count: evidence.legacy_count,
      canonical_count: evidence.canonical_count,
      mirrored: evidence.mirrored,
    },
  }
}

export function sameCanonicalControl(left: unknown, right: unknown): boolean {
  const a = readCanonicalControl(left)
  const b = readCanonicalControl(right)
  if (!a || !b) return false
  return JSON.stringify(a) === JSON.stringify(b)
}
