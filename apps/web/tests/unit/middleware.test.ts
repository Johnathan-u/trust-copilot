import { NextRequest } from 'next/server'
import { describe, expect, it } from 'vitest'

import { config, middleware } from '@/middleware'

function request(path: string, cookie?: string) {
  const headers = new Headers()
  if (cookie) headers.set('cookie', cookie)
  return new NextRequest(new URL(path, 'http://tc.test'), { headers })
}

describe('auth middleware', () => {
  it('redirects anonymous visitors to /login and keeps the requested path', () => {
    const res = middleware(request('/dashboard/review/12?tab=open'))
    expect(res.status).toBe(307)
    const location = new URL(res.headers.get('location') ?? '')
    expect(location.pathname).toBe('/login')
    expect(location.searchParams.get('next')).toBe('/dashboard/review/12')
  })

  it('does not accept a look-alike cookie as a session', () => {
    const res = middleware(request('/dashboard', 'tc_session_old=1; other=2'))
    expect(res.status).toBe(307)
  })

  it('lets requests with a session cookie through', () => {
    const res = middleware(
      request('/dashboard', 'tc_session=synthetic-test-value')
    )
    expect(res.status).toBe(200)
    expect(res.headers.get('location')).toBeNull()
    expect(res.headers.get('x-middleware-next')).toBe('1')
  })

  it('protects the dashboard, questionnaire and onboarding trees only', () => {
    expect(config.matcher).toEqual([
      '/dashboard/:path*',
      '/questionnaires/:path*',
      '/onboarding/:path*',
    ])
  })
})
