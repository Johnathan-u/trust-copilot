/**
 * Proxy all /api/* to the backend, forwarding cookies and headers so login, /auth/me,
 * export, download, and other requests work when the browser hits Next.js.
 */

import { NextRequest, NextResponse } from 'next/server'

import {
  isUploadTooLarge,
  limitRequestBody,
  maxUploadBytes,
  uploadLimitDetail,
} from '@/lib/upload-limit'

const API_UPSTREAM = process.env.API_UPSTREAM || 'http://localhost:8000'

function declaredLength(request: NextRequest): number | null {
  const raw = request.headers.get('content-length')
  if (raw == null || !/^\d+$/.test(raw.trim())) return null
  const value = Number(raw.trim())
  if (!Number.isSafeInteger(value)) return null
  return value
}

function buildBackendUrl(
  path: string[],
  searchParams: URLSearchParams
): string {
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

  const maxBytes = maxUploadBytes()
  let body: ReadableStream<Uint8Array> | undefined
  // GET has no body. Any other method streams, with a hard stop at MAX_UPLOAD_BYTES.
  if (method !== 'GET' && method !== 'HEAD') {
    const declared = declaredLength(request)
    if (declared != null && declared > maxBytes) {
      return NextResponse.json(
        { detail: uploadLimitDetail(maxBytes) },
        { status: 413 }
      )
    }
    if (request.body) {
      body = limitRequestBody(request.body, maxBytes)
    }
  }

  let res: Response
  try {
    res = await fetch(
      url,
      body
        ? ({
            method,
            headers,
            body,
            duplex: 'half',
            cache: 'no-store',
          } as RequestInit)
        : { method, headers, cache: 'no-store' }
    )
  } catch (err) {
    if (isUploadTooLarge(err)) {
      return NextResponse.json(
        { detail: uploadLimitDetail(maxBytes) },
        { status: 413 }
      )
    }
    // Backend unreachable (ECONNREFUSED, etc.) — return 502 so the client gets a proper response
    // instead of an unhandled exception that surfaces as "Failed to fetch".
    return NextResponse.json(
      {
        detail: 'Backend unavailable. Ensure the API is running on port 8000.',
      },
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
