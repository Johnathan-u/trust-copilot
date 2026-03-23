/**
 * Proxy all /api/* to the backend, forwarding cookies and headers so login, /auth/me,
 * export, download, and other requests work when the browser hits Next.js.
 */

import { NextRequest, NextResponse } from 'next/server'

const API_UPSTREAM = process.env.API_UPSTREAM || 'http://localhost:8000'

function buildBackendUrl(path: string[], searchParams: URLSearchParams): string {
  const pathStr = path.length ? path.join('/') : ''
  const query = searchParams.toString()
  const base = API_UPSTREAM.replace(/\/$/, '')
  return query ? `${base}/api/${pathStr}?${query}` : `${base}/api/${pathStr}`
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return proxy(request, context, 'GET')
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return proxy(request, context, 'POST')
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return proxy(request, context, 'PATCH')
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return proxy(request, context, 'PUT')
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return proxy(request, context, 'DELETE')
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
  method: string
) {
  const { path = [] } = await context.params
  const url = buildBackendUrl(path, request.nextUrl.searchParams)

  const headers: HeadersInit = {}
  const cookie = request.headers.get('cookie')
  if (cookie) headers['Cookie'] = cookie
  const authorization = request.headers.get('authorization')
  if (authorization) headers['Authorization'] = authorization
  // Browsers often omit Origin on same-origin fetch to Next.js; backend CSRF still needs a trusted Origin.
  const referer = request.headers.get('referer')
  let origin = request.headers.get('origin')
  if (!origin && referer) {
    try {
      origin = new URL(referer).origin
    } catch {
      /* ignore */
    }
  }
  if (!origin) {
    try {
      origin = new URL(request.url).origin
    } catch {
      /* ignore */
    }
  }
  if (origin) headers['Origin'] = origin
  if (referer) headers['Referer'] = referer
  const contentType = request.headers.get('content-type')
  if (contentType) headers['Content-Type'] = contentType

  let body: ArrayBuffer | undefined
  if (method !== 'GET') {
    try {
      // Use arrayBuffer so multipart/form-data (e.g. trust request with file) is forwarded correctly
      body = await request.arrayBuffer()
    } catch {
      body = undefined
    }
  }

  let res: Response
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body && body.byteLength > 0 ? body : undefined,
      cache: 'no-store',
    })
  } catch (err) {
    // Backend unreachable (ECONNREFUSED, etc.) — return 502 so the client gets a proper response
    // instead of an unhandled exception that surfaces as "Failed to fetch".
    return NextResponse.json(
      { detail: 'Backend unavailable. Ensure the API is running on port 8000.' },
      { status: 502 }
    )
  }

  const responseHeaders = new Headers()
  res.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (lower !== 'transfer-encoding') responseHeaders.set(key, value)
  })

  try {
    const responseBody = await res.arrayBuffer()
    return new NextResponse(responseBody, {
      status: res.status,
      statusText: res.statusText,
      headers: responseHeaders,
    })
  } catch {
    return NextResponse.json(
      { detail: 'Backend connection error while reading response.' },
      { status: 502 }
    )
  }
}
