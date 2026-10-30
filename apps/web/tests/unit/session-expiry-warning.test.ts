// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionExpiryWarning } from '@/components/layout/SessionExpiryWarning'

const auth = vi.hoisted(() => ({
  user: { id: 1 } as { id: number } | null,
  session_expiry: { expires_at: 2_000_000_600, deadline: 600_000 } as {
    expires_at: number
    deadline: number
  } | null,
  session_expiry_status: 'ready',
  refresh: vi.fn(),
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth }))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['performance', 'setTimeout', 'clearTimeout'] })
  auth.user = { id: 1 }
  auth.session_expiry = { expires_at: 2_000_000_600, deadline: 600_000 }
  auth.session_expiry_status = 'ready'
  auth.refresh.mockReset()
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

it('warns at five minutes, updates whole-minute text, and never offers extension', async () => {
  render(createElement(SessionExpiryWarning))
  expect(screen.queryByRole('status')).toBeNull()
  await act(async () => vi.advanceTimersByTimeAsync(300_000))
  const warning = screen.getByRole('status')
  expect(warning.textContent).toContain('about 5 minutes')
  expect(warning.textContent).toContain('Save your work')
  expect(warning.textContent).toContain('sign in again')
  expect(screen.queryByRole('button')).toBeNull()
  await act(async () => vi.advanceTimersByTimeAsync(240_001))
  expect(warning.textContent).toContain('less than a minute')
  await act(async () => vi.advanceTimersByTimeAsync(60_000))
  expect(warning.textContent).toContain('Checking')
  expect(warning.textContent).not.toContain('expires in')
})

it('offers an honest retry instead of retaining a stale countdown', () => {
  auth.session_expiry = null
  auth.session_expiry_status = 'unavailable'
  render(createElement(SessionExpiryWarning))
  expect(screen.getByRole('status').textContent).toContain('Could not check')
  fireEvent.click(screen.getByRole('button', { name: 'Check session' }))
  expect(auth.refresh).toHaveBeenCalledTimes(1)
})

it('announces a pending server check without declaring expiry or renewal', () => {
  auth.session_expiry = null
  auth.session_expiry_status = 'checking'
  render(createElement(SessionExpiryWarning))
  expect(screen.getByRole('status').textContent).toContain('Checking')
  expect(screen.queryByRole('button')).toBeNull()
})

it('cleans its display timer and hides after sign-out', async () => {
  const view = render(createElement(SessionExpiryWarning))
  auth.user = null
  view.rerender(createElement(SessionExpiryWarning))
  expect(screen.queryByRole('status')).toBeNull()
  view.unmount()
  expect(vi.getTimerCount()).toBe(0)
})
