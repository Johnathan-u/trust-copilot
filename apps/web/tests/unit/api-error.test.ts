import { describe, expect, it } from 'vitest'

import { formatApiErrorDetail } from '@/lib/api-error'

describe('formatApiErrorDetail', () => {
  it('returns a string detail as-is', () => {
    expect(formatApiErrorDetail({ detail: 'Invalid credentials' })).toBe('Invalid credentials')
  })

  it('uses message when there is no detail', () => {
    expect(formatApiErrorDetail({ message: 'Proxy says no' })).toBe('Proxy says no')
  })

  it('prefers detail over message', () => {
    expect(formatApiErrorDetail({ detail: 'from detail', message: 'from message' })).toBe(
      'from detail'
    )
  })

  it('returns the first FastAPI validation error message', () => {
    const data = {
      detail: [
        { loc: ['body', 'email'], msg: 'value is not a valid email address', type: 'value_error' },
        { loc: ['body', 'password'], msg: 'field required', type: 'missing' },
      ],
    }
    expect(formatApiErrorDetail(data)).toBe('value is not a valid email address')
  })

  it('serialises validation arrays without a usable msg', () => {
    expect(formatApiErrorDetail({ detail: [{ code: 42 }] })).toBe('[{"code":42}]')
  })

  it('reads msg from an object detail', () => {
    expect(formatApiErrorDetail({ detail: { msg: 'Workspace locked' } })).toBe('Workspace locked')
  })

  it.each([null, undefined, 'oops', 42, {}, { detail: [] }, { detail: { msg: 7 } }])(
    'falls back for unusable payload %j',
    (payload) => {
      expect(formatApiErrorDetail(payload)).toBe('Request failed')
      expect(formatApiErrorDetail(payload, 'Upload failed')).toBe('Upload failed')
    }
  )
})
