import { describe, expect, it } from 'vitest'
import {
  COMPLIANCE_ALERTS_SCHEMA,
  parseComplianceAlerts,
} from '@/lib/complianceAlertConsumer'

function body(alerts: unknown) {
  return { schema_version: COMPLIANCE_ALERTS_SCHEMA, alerts }
}

describe('parseComplianceAlerts', () => {
  it('reads the persisted alert and agrees on a second parse', () => {
    const payload = body([
      {
        id: 4,
        severity: 'high',
        title: 'Low coverage',
        description: 'Coverage is at 0%.',
        metric: 0,
        type: 'coverage_drop',
        status: 'active',
        condition: 'coverage_drop',
        source_ref: 'coverage',
        source_revision: 'abc',
        control_id: null,
        control_revision: null,
        reason: null,
        snoozed_until: null,
      },
    ])
    expect(parseComplianceAlerts(payload)).toEqual(
      parseComplianceAlerts(payload)
    )
    expect(parseComplianceAlerts(payload).alerts[0].control_id).toBeNull()
    expect(parseComplianceAlerts(payload).alerts[0].source_revision).toBe('abc')
  })

  it('skips a malformed alert and keeps the valid one', () => {
    const parsed = parseComplianceAlerts(
      body([
        { title: 'missing id' },
        {
          id: 9,
          severity: 'medium',
          title: 'Control evidence gap',
          description: 'An open control check still needs qualifying evidence.',
          metric: null,
          type: 'control_gap',
          status: 'active',
          condition: 'control_gap',
          source_ref: 'control:3',
          source_revision: 'rev-1',
          control_id: 3,
          control_revision: 'rev-1',
          reason: null,
          snoozed_until: null,
        },
      ])
    )
    expect(parsed.alerts.map((item) => item.id)).toEqual([9])
    expect(parsed.alerts[0].control_revision).toBe('rev-1')
  })

  it('rejects an unrecognized schema', () => {
    expect(() => parseComplianceAlerts(body([]))).not.toThrow()
    expect(() =>
      parseComplianceAlerts({ schema_version: 'other', alerts: [] })
    ).toThrow(/schema is not recognized/)
  })
})
