import { describe, expect, it } from 'vitest'
import { presentClaims, presentSecurityPage } from './securityPage.mjs'

function page(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 2,
    title: 'Security & Data Handling',
    subtitle: 'How we protect your data',
    notice: 'Only approved claims are shown as attested.',
    sections: [],
    certifications: [
      {
        name: 'SOC 2 Type II',
        status: 'attested',
        description: 'SOC 2 Type II report, period 2026',
        proof: { evidence_item_id: 41, title: 'SOC 2 report' },
      },
      {
        name: 'ISO 27001',
        status: 'not_attested',
        description: 'No ISO 27001 certification has been obtained.',
        proof: null,
      },
    ],
    infrastructure_highlights: ['TOTP multi-factor authentication'],
    contact: {
      security_email: 'security@example.com',
      dpa_available: true,
      subprocessor_list_available: false,
    },
    claims: [
      {
        key: 'soc2_type2',
        name: 'SOC 2 Type II',
        verified: true,
        proof: { evidence_item_id: 41, title: 'SOC 2 report' },
      },
      {
        key: 'security_contact',
        name: 'Security contact',
        verified: true,
        value: 'security@example.com',
      },
      { key: 'dpa', name: 'Data processing agreement', verified: true },
    ],
    ...overrides,
  }
}

describe('presentSecurityPage', () => {
  it('shows only verified claims backed by proof as attested', () => {
    const view = presentSecurityPage(page())
    expect(view.state).toBe('ready')
    expect(view.certifications.map((c) => [c.name, c.label])).toEqual([
      ['SOC 2 Type II', 'Attested'],
      ['ISO 27001', 'Not attested'],
    ])
    expect(view.certifications[0].proofTitle).toBe('SOC 2 report')
    expect(view.contact).toEqual({
      securityEmail: 'security@example.com',
      dpaAvailable: true,
      subprocessorListAvailable: false,
    })
  })

  it('refuses an attested status that has no matching verified claim', () => {
    const view = presentSecurityPage(page({ claims: [] }))
    expect(view.certifications[0].attested).toBe(false)
    expect(view.certifications[0].proofTitle).toBeNull()
    expect(view.contact.securityEmail).toBeNull()
    expect(view.contact.dpaAvailable).toBe(false)
  })

  it('refuses an attested status without a proof reference', () => {
    const tampered = page()
    tampered.certifications[0] = {
      ...tampered.certifications[0],
      proof: null,
    }
    expect(presentSecurityPage(tampered).certifications[0].attested).toBe(false)
  })

  it('rejects other schema versions and empty responses', () => {
    expect(presentSecurityPage(page({ schema_version: 1 })).state).toBe(
      'unsupported_schema'
    )
    expect(presentSecurityPage(null).state).toBe('unavailable')
    expect(presentSecurityPage(null).certifications).toEqual([])
  })
})

describe('presentClaims', () => {
  it('maps stored decisions for the editor', () => {
    const view = presentClaims({
      schema_version: 2,
      claims: [
        {
          key: 'backups',
          name: 'Automated backups and recovery',
          group: 'infrastructure',
          status: 'claimed',
          verified: false,
          reason: 'proof_unavailable',
          revision: 3,
          stored_statement: 'Nightly backups',
          stored_value: null,
          evidence_item_id: 9,
          proof_required: true,
        },
      ],
    })
    expect(view.rows).toEqual([
      {
        key: 'backups',
        name: 'Automated backups and recovery',
        group: 'infrastructure',
        status: 'claimed',
        verified: false,
        reasonLabel: 'Proof is missing or no longer approved',
        revision: 3,
        statement: 'Nightly backups',
        value: '',
        evidenceItemId: 9,
        proofRequired: true,
      },
    ])
    expect(presentClaims({ schema_version: 3 }).state).toBe(
      'unsupported_schema'
    )
  })
})
