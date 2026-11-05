// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import LoginPage from '@/app/login/page'

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(),
}))

vi.mock('next/navigation', () => ({
  useSearchParams: () => navigation.params,
}))

let loginBody: unknown = {}
let loginStatus = 200

beforeEach(() => {
  navigation.params = new URLSearchParams()
  loginBody = {}
  loginStatus = 200
  window.history.replaceState(null, '', '/login')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/auth/oauth/providers') {
        return Response.json({ google: false, github: false })
      }
      if (url === '/api/auth/login' && init?.method === 'POST') {
        return Response.json(loginBody, { status: loginStatus })
      }
      if (url === '/api/auth/mfa/verify-login' && init?.method === 'POST') {
        return Response.json({})
      }
      if (url === '/api/auth/mfa/setup' && init?.method === 'POST') {
        return Response.json({ secret: 'synthetic-secret' })
      }
      if (url === '/api/auth/mfa/confirm' && init?.method === 'POST') {
        return Response.json({ recovery_codes: ['recovery-one'] })
      }
      throw new Error(`Unexpected fetch ${init?.method ?? 'GET'} ${url}`)
    })
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function signIn() {
  render(createElement(LoginPage))
  await act(async () => {})
  fireEvent.change(screen.getByLabelText('Email'), {
    target: { value: 'ada@example.com' },
  })
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'secret' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await act(async () => {})
}

describe('sign-in next redirect', () => {
  it('honours a safe next path and ignores an unsafe one', async () => {
    navigation.params = new URLSearchParams(
      'next=/dashboard/review/12?tab=open#section'
    )
    await signIn()
    expect(window.location.origin).toBe('http://localhost:3000')
    expect(window.location.pathname).toBe('/dashboard/review/12')
    expect(window.location.search).toBe('?tab=open')
    expect(window.location.hash).toBe('#section')

    cleanup()
    window.history.replaceState(null, '', '/login')
    navigation.params = new URLSearchParams(
      'next=' + encodeURIComponent('https://example.com/phish')
    )
    await signIn()
    expect(window.location.origin).toBe('http://localhost:3000')
    expect(window.location.pathname).toBe('/dashboard')
    expect(window.location.search).toBe('')
    expect(window.location.hash).toBe('')
  })

  it('sends the MFA continuation to the same safe path', async () => {
    navigation.params = new URLSearchParams('next=/dashboard/security')
    loginBody = { requires_mfa: true, mfa_token: 'synthetic-token' }
    await signIn()
    expect(window.location.pathname).toBe('/login')

    fireEvent.change(screen.getByLabelText('Code'), {
      target: { value: '123456' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verify' }))
    await act(async () => {})

    expect(window.location.origin).toBe('http://localhost:3000')
    expect(window.location.pathname).toBe('/dashboard/security')
  })

  it('sends the MFA enrolment recovery-codes continuation through the validated next', async () => {
    navigation.params = new URLSearchParams('next=/dashboard/security')
    loginBody = { requires_mfa_enrol: true }
    await signIn()
    fireEvent.change(await screen.findByLabelText('Code'), {
      target: { value: '123456' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verify and continue' }))
    await act(async () => {})
    expect(window.location.pathname).toBe('/login')
    expect(screen.getByText('recovery-one')).toBeTruthy()

    fireEvent.click(
      screen.getByRole('button', { name: "I've saved these codes" })
    )
    await act(async () => {})
    expect(window.location.origin).toBe('http://localhost:3000')
    expect(window.location.pathname).toBe('/dashboard/security')

    cleanup()
    window.history.replaceState(null, '', '/login')
    navigation.params = new URLSearchParams(
      'next=' + encodeURIComponent('https://example.com/phish')
    )
    await signIn()
    fireEvent.change(await screen.findByLabelText('Code'), {
      target: { value: '123456' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Verify and continue' }))
    await act(async () => {})
    fireEvent.click(
      screen.getByRole('button', { name: "I've saved these codes" })
    )
    await act(async () => {})
    expect(window.location.origin).toBe('http://localhost:3000')
    expect(window.location.pathname).toBe('/dashboard')
    expect(window.location.search).toBe('')
    expect(window.location.hash).toBe('')
  })
})
