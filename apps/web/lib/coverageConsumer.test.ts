import { describe, expect, it } from 'vitest'
import {
  CONTROL_COVERAGE_SCHEMA,
  denominatorNotes,
  parseCoverageResponse,
} from '@/lib/coverageConsumer'

function body(overrides: Record<string, unknown> = {}) {
  return {
    kpi: { total_questions: 4, coverage_pct: 50 },
    framework_coverage: [{ framework: 'Synthetic', total: 2, drafted: 1 }],
    blind_spots: [],
    weak_areas: [],
    evidence_strength: [],
    recommended_evidence: [
      { title: 'Synthetic policy', improves_questions: 1 },
    ],
    trends: [],
    drill_down: [],
    control_coverage: {
      schema_version: CONTROL_COVERAGE_SCHEMA,
      numerator: 1,
      denominator: 2,
      coverage_pct: 50,
      qualified_control_ids: [7],
      explanations: [
        {
          control_id: 7,
          state: 'qualified',
          rule: 'evidence_qualifies',
          effect: 'counted',
          denominator_changed: false,
          framework_id: null,
        },
        {
          control_id: 8,
          state: 'disabled',
          rule: 'lifecycle_disabled',
          effect: 'excluded_from_denominator',
          denominator_changed: true,
          framework_id: null,
        },
        {
          control_id: 9,
          state: 'stale',
          rule: 'expired',
          effect: 'excluded_from_numerator',
          denominator_changed: false,
          framework_id: 3,
        },
      ],
    },
    ...overrides,
  }
}

describe('parseCoverageResponse', () => {
  it('keeps the existing fields and the versioned control denominator', () => {
    const parsed = parseCoverageResponse(body())
    expect(parsed.kpi).toEqual({ total_questions: 4, coverage_pct: 50 })
    expect(parsed.framework_coverage).toEqual([
      { framework: 'Synthetic', total: 2, drafted: 1 },
    ])
    expect(parsed.recommended_evidence).toEqual([
      {
        title: 'Synthetic policy',
        improves_questions: 1,
        evidence_ids: [],
        control_ids: [],
        question_ids: [],
      },
    ])
    expect(parsed.control_coverage.schema_version).toBe(CONTROL_COVERAGE_SCHEMA)
    expect(parsed.control_coverage.numerator).toBe(1)
    expect(parsed.control_coverage.denominator).toBe(2)
    expect(parsed.control_coverage.qualified_control_ids).toEqual([7])
  })

  it('agrees across a second parse of the same payload', () => {
    const payload = body()
    expect(parseCoverageResponse(payload)).toEqual(
      parseCoverageResponse(payload)
    )
  })

  it('reads provenance ids and leaves a sourceless recommendation empty', () => {
    const parsed = parseCoverageResponse(
      body({
        recommended_evidence: [
          {
            title: 'Synthetic policy',
            improves_questions: 2,
            evidence_ids: [11],
            control_ids: [22],
            question_ids: [33],
          },
          { title: 'No source', improves_questions: 0 },
        ],
      })
    )
    expect(parsed.recommended_evidence[0]).toEqual({
      title: 'Synthetic policy',
      improves_questions: 2,
      evidence_ids: [11],
      control_ids: [22],
      question_ids: [33],
    })
    expect(parsed.recommended_evidence[1].evidence_ids).toEqual([])
    expect(parsed.recommended_evidence[1].control_ids).toEqual([])
    expect(parsed.recommended_evidence[1].question_ids).toEqual([])
    expect(() =>
      parseCoverageResponse(
        body({
          recommended_evidence: [
            {
              title: 'Synthetic policy',
              improves_questions: 1,
              evidence_ids: ['11'],
            },
          ],
        })
      )
    ).toThrow(/evidence ids/)
  })

  it('rejects a missing or unversioned control denominator', () => {
    const missing = body()
    delete (missing as { control_coverage?: unknown }).control_coverage
    expect(() => parseCoverageResponse(missing)).toThrow(
      /control coverage is missing/
    )
    expect(() =>
      parseCoverageResponse(
        body({
          control_coverage: {
            ...(body().control_coverage as object),
            schema_version: 'other',
          },
        })
      )
    ).toThrow(/schema is not recognized/)
  })

  it('explains disabled, unknown, stale, and denominator changes', () => {
    const notes = denominatorNotes(
      parseCoverageResponse(body()).control_coverage
    )
    expect(notes.map((item) => item.state)).toEqual(['disabled', 'stale'])
    expect(notes[0].denominator_changed).toBe(true)
  })
})
