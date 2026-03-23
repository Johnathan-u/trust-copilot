import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PROTECTED_PREFIXES = ['/dashboard', '/questionnaires']

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname === '/login') {
    return NextResponse.next()
  }
  const isProtected = PROTECTED_PREFIXES.some((p) =>
    request.nextUrl.pathname.startsWith(p)
  )
  if (!isProtected) return NextResponse.next()
  const hasSession = request.cookies.has('tc_session')
  if (!hasSession) {
    const login = new URL('/login', request.url)
    login.searchParams.set('next', request.nextUrl.pathname)
    return NextResponse.redirect(login)
  }
  return NextResponse.next()
}
