import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The route reads API_UPSTREAM at import time, so set it before importing.
vi.stubEnv('API_UPSTREAM', 'http://upstream.test/')
const route = await import('@/app/api/[[...path]]/route')

type FetchArgs = [string, RequestInit]

const fetchMock = vi.fn<(...args: FetchArgs) => Promise<Response>>()

function ctx(path?: string[]) {
  return { params: Promise.resolve(path ? { path } : {}) }
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('/api proxy route', () => {
  it('forwards path, query, cookies and auth headers to the upstream API', async () => {
    fetchMock.mockResolvedValue(
      new Response('{"ok":true}', {
        status: 200,
        headers: {
          'content-type': 'application/json',
          'transfer-encoding': 'chunked',
          'x-req': 'r1',
        },
      })
    )
    const req = new NextRequest('http://tc.test/api/auth/me?verbose=1', {
      headers: {
        cookie: 'tc_session=synthetic',
        authorization: 'Bearer synthetic-token',
      },
    })

    const res = await route.GET(req, ctx(['auth', 'me']))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://upstream.test/api/auth/me?verbose=1')
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
    expect(init.cache).toBe('no-store')
    const headers = init.headers as Record<string, string>
    expect(headers.Cookie).toBe('tc_session=synthetic')
    expect(headers.Authorization).toBe('Bearer synthetic-token')
    // No Origin/Referer from the browser: fall back to the request origin for backend CSRF.
    expect(headers.Origin).toBe('http://tc.test')

    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })
    expect(res.headers.get('x-req')).toBe('r1')
    expect(res.headers.get('transfer-encoding')).toBeNull()
  })

  it('derives Origin from Referer and forwards a POST body', async () => {
    fetchMock.mockResolvedValue(new Response('{"id":3}', { status: 201 }))
    const req = new NextRequest('http://tc.test/api/answers/3', {
      method: 'POST',
      headers: {
        referer: 'https://app.tc.test/dashboard/review/3',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ text: 'synthetic answer' }),
    })

    const res = await route.POST(req, ctx(['answers', '3']))

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('http://upstream.test/api/answers/3')
    const headers = init.headers as Record<string, string>
    expect(headers.Origin).toBe('https://app.tc.test')
    expect(headers.Referer).toBe('https://app.tc.test/dashboard/review/3')
    expect(headers['Content-Type']).toBe('application/json')
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(
      '{"text":"synthetic answer"}'
    )
    expect(res.status).toBe(201)
    expect(await res.json()).toEqual({ id: 3 })
  })

  it('passes upstream error statuses through unchanged', async () => {
    fetchMock.mockResolvedValue(
      new Response('{"detail":"Forbidden"}', { status: 403 })
    )
    const res = await route.DELETE(
      new NextRequest('http://tc.test/api/members/9', { method: 'DELETE' }),
      ctx(['members', '9'])
    )
    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({ detail: 'Forbidden' })
  })

  it('returns 502 with a JSON detail when the upstream is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'))
    const res = await route.GET(
      new NextRequest('http://tc.test/api/health'),
      ctx(['health'])
    )
    expect(res.status).toBe(502)
    expect((await res.json()).detail).toMatch(/Backend unavailable/)
  })

  it('maps an empty catch-all path to the API root', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }))
    await route.GET(new NextRequest('http://tc.test/api'), ctx())
    expect(fetchMock.mock.calls[0][0]).toBe('http://upstream.test/api/')
  })
})
