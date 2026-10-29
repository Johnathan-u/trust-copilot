import { describe, expect, it } from 'vitest'

import {
  ApiRequestError,
  MALFORMED_RESPONSE_DESCRIPTION,
  formatApiErrorDetail,
  mutationFailureNotice,
  presentActionFailure,
  presentHttpFailure,
} from '@/lib/api-error'
import { readSectionJson } from '@/lib/section-load'

describe('formatApiErrorDetail', () => {
  it('returns a string detail as-is', () => {
    expect(formatApiErrorDetail({ detail: 'Invalid credentials' })).toBe(
      'Invalid credentials'
    )
  })

  it('uses message when there is no detail', () => {
    expect(formatApiErrorDetail({ message: 'Proxy says no' })).toBe(
      'Proxy says no'
    )
  })

  it('prefers detail over message', () => {
    expect(
      formatApiErrorDetail({ detail: 'from detail', message: 'from message' })
    ).toBe('from detail')
  })

  it('returns the first FastAPI validation error message', () => {
    const data = {
      detail: [
        {
          loc: ['body', 'email'],
          msg: 'value is not a valid email address',
          type: 'value_error',
        },
        { loc: ['body', 'password'], msg: 'field required', type: 'missing' },
      ],
    }
    expect(formatApiErrorDetail(data)).toBe(
      'value is not a valid email address'
    )
  })

  it('serialises validation arrays without a usable msg', () => {
    expect(formatApiErrorDetail({ detail: [{ code: 42 }] })).toBe(
      '[{"code":42}]'
    )
  })

  it('reads msg from an object detail', () => {
    expect(formatApiErrorDetail({ detail: { msg: 'Workspace locked' } })).toBe(
      'Workspace locked'
    )
  })

  it.each([
    null,
    undefined,
    'oops',
    42,
    {},
    { detail: [] },
    { detail: { msg: 7 } },
  ])('falls back for unusable payload %j', (payload) => {
    expect(formatApiErrorDetail(payload)).toBe('Request failed')
    expect(formatApiErrorDetail(payload, 'Upload failed')).toBe('Upload failed')
  })
})

const LEAKS = [
  'permission',
  'forbidden',
  'unauthorized',
  'insufficient',
  'can_admin',
  'can_edit',
  'scope',
  '403',
  '404',
  '500',
  '502',
  'admin',
  'role',
]

describe('presentHttpFailure', () => {
  it('maps offline, 403, 404, and 5xx to distinct neutral copy', () => {
    const offline = presentHttpFailure({ offline: true })
    const forbidden = presentHttpFailure({ status: 403 })
    const missing = presentHttpFailure({ status: 404 })
    const server = presentHttpFailure({ status: 500 })
    const gateway = presentHttpFailure({ status: 502 })

    expect(offline.kind).toBe('offline')
    expect(forbidden.kind).toBe('forbidden')
    expect(missing.kind).toBe('not_found')
    expect(server.kind).toBe('server')
    expect(gateway.kind).toBe('server')
    expect(
      new Set([offline.title, forbidden.title, missing.title, server.title])
        .size
    ).toBe(4)
    expect(server.title).toBe(gateway.title)
    expect(server.description).not.toBe(forbidden.description)
    expect(missing.description).not.toBe(offline.description)
  })

  it('does not echo response bodies or permission internals', () => {
    const cases = [
      presentHttpFailure({ status: 403 }),
      presentHttpFailure({ status: 404 }),
      presentHttpFailure({ status: 500 }),
      presentHttpFailure({ status: 503 }),
      presentHttpFailure({ offline: true }),
      presentHttpFailure({ status: 401 }),
      presentHttpFailure({ status: 422 }),
      presentHttpFailure({ malformed: true }),
      presentHttpFailure({ status: 0 }),
    ]
    for (const failure of cases) {
      const text = `${failure.title} ${failure.description}`.toLowerCase()
      for (const leak of LEAKS) {
        expect(text, text).not.toContain(leak)
      }
    }
    expect(presentHttpFailure({ malformed: true }).description).toBe(
      MALFORMED_RESPONSE_DESCRIPTION
    )
    expect(presentHttpFailure({ status: 0 }).kind).toBe('offline')
    expect(presentHttpFailure({ offline: true, status: 500 }).kind).toBe(
      'offline'
    )
  })

  it('keeps the server detail out of the thrown request error', async () => {
    const response = new Response(
      JSON.stringify({ detail: 'Insufficient permissions for admin role' }),
      { status: 403, headers: { 'content-type': 'application/json' } }
    )
    await expect(readSectionJson(response)).rejects.toBeInstanceOf(
      ApiRequestError
    )
    try {
      await readSectionJson(
        new Response(JSON.stringify({ detail: 'Insufficient permissions' }), {
          status: 403,
        })
      )
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError)
      const failure = (error as ApiRequestError).failure
      expect(failure.kind).toBe('forbidden')
      expect(failure.title).not.toMatch(/permission/i)
      expect((error as Error).message).not.toMatch(/permission/i)
    }
  })
})

const ACTION_LEAKS = [
  ...LEAKS,
  'corrupt',
  'definitely',
  'does not exist',
  'guaranteed',
]

describe('presentActionFailure', () => {
  it('gives the four failures distinct next steps', () => {
    const model = presentActionFailure({
      status: 400,
      data: { detail: 'Unsupported model' },
    })
    const format = presentActionFailure({
      status: 400,
      data: {
        detail:
          'File must have an allowed extension. Allowed: .docx, .pdf, .xlsx',
      },
    })
    const evidence = presentActionFailure({
      data: {
        code: 'no_evidence',
        message:
          'No eligible evidence was found for this question, so no model call was made.',
      },
    })
    const denied = presentActionFailure({
      status: 403,
      data: { detail: 'Insufficient permissions for admin role' },
    })

    expect(model?.kind).toBe('unsupported_model')
    expect(format?.kind).toBe('unsupported_format')
    expect(evidence?.kind).toBe('no_evidence')
    expect(denied?.kind).toBe('permission')
    expect(
      new Set([model?.title, format?.title, evidence?.title, denied?.title])
        .size
    ).toBe(4)
    expect(
      new Set([
        model?.message,
        format?.message,
        evidence?.message,
        denied?.message,
      ]).size
    ).toBe(4)

    for (const failure of [model, format, evidence, denied]) {
      const text = `${failure?.title} ${failure?.message}`.toLowerCase()
      for (const leak of ACTION_LEAKS) {
        expect(text, text).not.toContain(leak)
      }
      expect(text).not.toContain('allowed:')
      expect(text).not.toContain('admin role')
    }
    expect(model?.message).toMatch(/supported model/i)
    expect(format?.message).toMatch(/supported format/i)
    expect(evidence?.message).toMatch(/add evidence/i)
    expect(denied?.message).toMatch(/try again/i)
  })

  it('does not treat nearby failures as one of the four', () => {
    expect(
      presentActionFailure({
        data: {
          code: 'model_abstained',
          message:
            'The model reviewed the supplied evidence and judged it insufficient to answer.',
        },
      })
    ).toBeNull()
    expect(
      presentActionFailure({
        data: { code: 'model_error', message: 'The model call failed.' },
      })
    ).toBeNull()
    expect(
      presentActionFailure({
        status: 400,
        data: { detail: 'The unsupported model setting might be wrong later' },
      })
    ).toBeNull()
    expect(
      presentActionFailure({ status: 401, data: { detail: 'Sign in' } })
    ).toBeNull()
    expect(
      presentActionFailure({ status: 500, data: { detail: 'boom' } })
    ).toBeNull()
    expect(presentActionFailure({ status: 422, data: {} })).toBeNull()
  })

  it('recognises format and model codes without copying them into the sentence', () => {
    expect(
      presentActionFailure({ data: { error_code: 'model_unavailable' } })?.kind
    ).toBe('unsupported_model')
    expect(
      presentActionFailure({
        data: { detail: 'format must be xlsx or docx' },
      })?.kind
    ).toBe('unsupported_format')
    expect(
      presentActionFailure({ data: { outcome_code: 'no_evidence' } })?.message
    ).not.toMatch(/model call/i)
    const notice = mutationFailureNotice(
      403,
      { detail: 'Insufficient permissions for admin role' },
      'Upload failed'
    )
    expect(notice.title).toBe('Action not available')
    expect(notice.message).not.toMatch(/admin/i)
    expect(
      mutationFailureNotice(400, { detail: 'Title is required' }, 'Save failed')
    ).toEqual({
      title: 'Could not complete that',
      message: 'Title is required',
    })
  })
})
