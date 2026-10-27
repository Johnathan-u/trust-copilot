import { describe, expect, it } from 'vitest'
import {
  CASE_STUDY_SCHEMA_VERSION,
  PRESERVED_FIELDS,
  displayLabel,
  outcomesAgree,
  parseCaseStudyError,
  parseCaseStudyResponse,
} from '@/lib/caseStudyConsumer'

function body(
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    id: 7,
    workspace_id: 3,
    title: 'Synthetic rollout',
    company_name: 'Example Org',
    industry: 'Software',
    company_size: '51-200',
    challenge: 'Slow reviews',
    solution: 'Automated answers',
    results: 'Faster reviews',
    quote: 'It helped.',
    quote_attribution: 'Synthetic Person',
    metrics: { hours_saved: 10 },
    status: 'published',
    published_at: '2026-10-27T00:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    schema_version: CASE_STUDY_SCHEMA_VERSION,
    synthetic: false,
    data_basis: 'consented_customer',
    customer_claim: true,
    publication_authorized: true,
    review_status: 'approved',
    revision: 2,
    quoted_organizations: ['Example Org'],
    quoted_results: ['Faster reviews'],
    blockers: [],
    ...overrides,
  }
}

describe('displayLabel', () => {
  it('labels only a non-synthetic consented customer claim as a publication', () => {
    expect(
      displayLabel({
        customer_claim: true,
        synthetic: false,
        data_basis: 'consented_customer',
      })
    ).toBe('Consented publication')
  })

  it('labels synthetic rows as synthetic examples even when a claim is asserted', () => {
    expect(
      displayLabel({
        customer_claim: true,
        synthetic: true,
        data_basis: 'consented_customer',
      })
    ).toBe('Synthetic example. Not a customer claim.')
    expect(
      displayLabel({
        customer_claim: false,
        synthetic: false,
        data_basis: 'synthetic_example',
      })
    ).toBe('Synthetic example. Not a customer claim.')
  })

  it('falls back to not a customer claim for other bases', () => {
    expect(
      displayLabel({
        customer_claim: false,
        synthetic: false,
        data_basis: 'consented_customer',
      })
    ).toBe('Not a customer claim.')
    expect(
      displayLabel({ customer_claim: true, synthetic: false, data_basis: '' })
    ).toBe('Not a customer claim.')
  })
})

describe('parseCaseStudyResponse', () => {
  it('parses an authorized consented publication as a customer claim', () => {
    const view = parseCaseStudyResponse(body())
    expect(view.customer_claim).toBe(true)
    expect(view.display_label).toBe('Consented publication')
    expect(view.id).toBe(7)
    expect(view.workspace_id).toBe(3)
    expect(view.revision).toBe(2)
    expect(view.schema_version).toBe(CASE_STUDY_SCHEMA_VERSION)
    expect(view.published_at).toBe('2026-10-27T00:00:00Z')
    expect(view.metrics).toEqual({ hours_saved: 10 })
    expect(view.quoted_organizations).toEqual(['Example Org'])
    expect(view.quoted_results).toEqual(['Faster reviews'])
  })

  it('rejects non-objects, wrong schema versions and missing preserved fields', () => {
    expect(() => parseCaseStudyResponse(null)).toThrow(
      'case study response must be an object'
    )
    expect(() => parseCaseStudyResponse('x')).toThrow(
      'case study response must be an object'
    )
    expect(() =>
      parseCaseStudyResponse(body({ schema_version: 'case-study.v1' }))
    ).toThrow('schema_version mismatch')
    for (const field of PRESERVED_FIELDS) {
      const rec = body()
      delete rec[field]
      expect(() => parseCaseStudyResponse(rec)).toThrow(
        `missing preserved field ${field}`
      )
    }
  })

  it('accepts preserved fields that are present but null', () => {
    const view = parseCaseStudyResponse(
      body({
        published_at: null,
        quote: null,
        metrics: null,
        company_name: null,
      })
    )
    expect(view.published_at).toBeNull()
    expect(view.quote).toBeNull()
    expect(view.metrics).toBeNull()
    expect(view.company_name).toBeNull()
  })

  it.each([
    ['synthetic row', { synthetic: true }],
    ['synthetic basis', { data_basis: 'synthetic_example' }],
    ['draft status', { status: 'draft' }],
    ['unauthorized publication', { publication_authorized: false }],
    ['truthy but non-boolean claim', { customer_claim: 'true' }],
    ['truthy but non-boolean authorization', { publication_authorized: 1 }],
  ])('does not treat a %s as a customer claim', (_name, overrides) => {
    const view = parseCaseStudyResponse(body(overrides))
    expect(view.customer_claim).toBe(false)
    expect(view.display_label).not.toBe('Consented publication')
  })

  it('labels a synthetic row as a synthetic example', () => {
    const view = parseCaseStudyResponse(
      body({ synthetic: true, data_basis: 'synthetic_example' })
    )
    expect(view.synthetic).toBe(true)
    expect(view.display_label).toBe('Synthetic example. Not a customer claim.')
  })

  it('coerces malformed optional fields to safe defaults', () => {
    const view = parseCaseStudyResponse(
      body({
        title: 42,
        status: undefined,
        data_basis: 5,
        review_status: null,
        published_at: 123,
        company_name: 9,
        results: ['x'],
        metrics: 'many',
        quoted_organizations: ['Example Org', 3, null],
        quoted_results: 'Faster reviews',
        blockers: [
          null,
          'oops',
          {
            field: 'quote',
            code: 'consent_missing',
            organization_name: 'Org B',
          },
          { field: 1, code: null },
        ],
      })
    )
    expect(view.title).toBe('')
    expect(view.status).toBe('')
    expect(view.data_basis).toBe('')
    expect(view.review_status).toBe('')
    expect(view.published_at).toBeNull()
    expect(view.company_name).toBeNull()
    expect(view.results).toBeNull()
    expect(view.metrics).toBeNull()
    expect(view.customer_claim).toBe(false)
    expect(view.display_label).toBe('Not a customer claim.')
    expect(view.quoted_organizations).toEqual(['Example Org'])
    expect(view.quoted_results).toEqual([])
    expect(view.blockers).toEqual([
      { field: 'quote', code: 'consent_missing', organization_name: 'Org B' },
      { field: '', code: '', organization_name: null },
    ])
  })
})

describe('parseCaseStudyError', () => {
  it('maps FastAPI validation arrays to a non-retryable validation error', () => {
    expect(
      parseCaseStudyError({ detail: [{ msg: 'field required' }, { msg: 'x' }] })
    ).toEqual({
      code: 'validation_error',
      message: 'field required',
      retryable: false,
      field_errors: [],
    })
    expect(parseCaseStudyError({ detail: [{}] }).message).toBe('Request failed')
  })

  it('reads structured detail with field errors', () => {
    expect(
      parseCaseStudyError({
        detail: {
          code: 'consent_required',
          message: 'Consent is missing',
          retryable: true,
          field_errors: [
            { field: 'quote', code: 'no_consent', organization_name: 'Org B' },
            { field: 'results' },
            null,
          ],
        },
      })
    ).toEqual({
      code: 'consent_required',
      message: 'Consent is missing',
      retryable: true,
      field_errors: [
        { field: 'quote', code: 'no_consent', organization_name: 'Org B' },
        { field: 'results', code: '', organization_name: null },
      ],
    })
  })

  it('reads a top-level error body and msg fallback', () => {
    const err = parseCaseStudyError({ code: 'conflict', msg: 'Stale revision' })
    expect(err.code).toBe('conflict')
    expect(err.message).toBe('Stale revision')
    expect(err.retryable).toBe(false)
  })

  it('defaults unknown or empty bodies', () => {
    const expected = {
      code: 'unknown',
      message: 'Request failed',
      retryable: false,
      field_errors: [],
    }
    expect(parseCaseStudyError(null)).toEqual(expected)
    expect(parseCaseStudyError('boom')).toEqual(expected)
    expect(parseCaseStudyError({ detail: [] })).toEqual(expected)
    expect(parseCaseStudyError({ detail: 'Not found' })).toEqual(expected)
    expect(parseCaseStudyError({ retryable: 'yes' }).retryable).toBe(false)
  })
})

describe('outcomesAgree', () => {
  function persistedFrom(api: Record<string, unknown>) {
    const view = parseCaseStudyResponse(api)
    return { ...api, display_label: view.display_label }
  }

  it('agrees when the API body, parsed view and persisted row match', () => {
    const api = body({ display_label: 'Consented publication' })
    expect(outcomesAgree(api, persistedFrom(api))).toEqual({
      agrees: true,
      mismatches: [],
    })
  })

  it('reports fields where the persisted row differs', () => {
    const api = body({ display_label: 'Consented publication' })
    const stored = { ...persistedFrom(api), revision: 3, status: 'draft' }
    expect(outcomesAgree(api, stored)).toEqual({
      agrees: false,
      mismatches: ['status', 'revision'],
    })
  })

  it('flags an API claim the consumer does not honour', () => {
    const api = body({
      synthetic: true,
      customer_claim: true,
      display_label: 'Consented publication',
    })
    const result = outcomesAgree(api, { ...api })
    expect(result.agrees).toBe(false)
    expect(result.mismatches).toEqual(['customer_claim', 'display_label'])
  })

  it('propagates parse failures for invalid API bodies', () => {
    expect(() =>
      outcomesAgree(body({ schema_version: 'nope' }), body())
    ).toThrow('schema_version mismatch')
  })
})
