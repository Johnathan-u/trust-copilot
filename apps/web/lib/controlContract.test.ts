import { describe, expect, it } from 'vitest'
import {
  readCanonicalControl,
  sameCanonicalControl,
  type CanonicalControl,
} from '@/lib/controlContract'

function row(overrides: Record<string, unknown> = {}) {
  const canonical: CanonicalControl = {
    contract_version: 'control-contract/v1',
    id: 'TC21002:C-1',
    version: null,
    content_version: null,
    owner_user_id: 4,
    owner_team: 'owners',
    lifecycle: 'in_progress',
    status_aligned: true,
    evidence: {
      contract_version: 'control-evidence/v1',
      workspace_scoped: true,
      exactly_one_target: true,
      legacy_count: 0,
      canonical_count: 0,
      mirrored: true,
    },
  }
  return {
    id: 1,
    status: 'in_review',
    canonical: { ...canonical, ...overrides },
  }
}

describe('control contract consumer', () => {
  it('reads the same canonical block from either route payload', () => {
    const legacy = row()
    const compliance = {
      id: 99,
      status: 'in_progress',
      framework: null,
      canonical: legacy.canonical,
    }
    expect(sameCanonicalControl(legacy, compliance)).toBe(true)
    expect(readCanonicalControl(legacy)?.version).toBeNull()
    expect(readCanonicalControl(legacy)?.lifecycle).toBe('in_progress')
  })

  it('rejects a licensed version and a divergent contract', () => {
    expect(
      readCanonicalControl(row({ version: '2026', content_version: '2026' }))
    ).toBeNull()
    expect(readCanonicalControl({ id: 1, status: 'in_review' })).toBeNull()
    expect(readCanonicalControl(row({ lifecycle: 'enabled' }))).toBeNull()
  })
})
