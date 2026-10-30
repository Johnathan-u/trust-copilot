// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SecurityPage from '@/app/dashboard/security/page'

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    mfa_enrolled: true,
    permissions: { can_admin: false },
    workspace_auth_policy: {
      mfa_required: false,
      session_max_age_seconds: null,
    },
    refresh: async () => {},
  }),
}))

const current = {
  id: 1,
  session_id: 'first…',
  current: true,
  user_agent: 'Chrome/130 Linux',
  ip_address: null,
  created_at: null,
}
const other = { ...current, id: 2, session_id: 'second…', current: false }
const path = '/api/auth/sessions/revoke-all'
const unconfirmed = 'Could not confirm sign-out. Try again or sign in again.'
let sessions = [current, other]
let mutate: (url: string) => Promise<Response>
let fetchMock: ReturnType<typeof vi.fn>
let navigate: ReturnType<typeof vi.spyOn>

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  sessions = [current, other]
  mutate = async () => json({ ok: true, revoked: 2 })
  navigate = vi.spyOn(window.location, 'replace').mockImplementation(() => {})
  fetchMock = vi.fn(
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = String(input)
      if (init.method === 'POST') return mutate(url)
      if (url === '/api/auth/sessions') return json({ sessions })
      if (url === '/api/auth/mfa/status') return json({ enabled: true })
      throw new Error(`Unexpected read ${url}`)
    }
  )
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function open() {
  render(createElement(SecurityPage))
  const trigger = await screen.findByRole('button', {
    name: 'Sign out everywhere',
  })
  // happy-dom has no layout; real Chromium controls verify actual return focus.
  vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue(
    new DOMRect(0, 0, 180, 32)
  )
  trigger.focus()
  fireEvent.click(trigger)
  const dialog = await screen.findByRole('alertdialog', {
    name: 'Sign out everywhere?',
  })
  return {
    trigger,
    dialog,
    confirm: within(dialog).getByRole('button', {
      name: 'Sign out everywhere',
    }),
  }
}

function writes() {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
}

describe('logout-all mocked response controls (not real API/browser qualification)', () => {
  it('starts on Cancel and cancellation sends no mutation', async () => {
    const { trigger, dialog } = await open()
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(dialog).getByRole('button', { name: 'Cancel' })
      )
    )
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(writes()).toHaveLength(0)
    expect(navigate).not.toHaveBeenCalled()
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it('guards synchronous repeated confirmation and both actions until acknowledgment', async () => {
    let release!: (response: Response) => void
    mutate = () =>
      new Promise<Response>((resolve) => {
        release = resolve
      })
    const { confirm } = await open()
    const others = screen.getByRole('button', {
      name: /Sign out all other devices/,
      hidden: true,
    }) as HTMLButtonElement
    act(() => {
      fireEvent.click(confirm)
      fireEvent.click(confirm)
    })
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toEqual([
      path,
      { method: 'POST', credentials: 'include' },
    ])
    expect(others.disabled).toBe(true)
    await act(async () => {})
    const pendingDialog = screen.getByRole('alertdialog')
    expect(
      (
        within(pendingDialog).getByRole('button', {
          name: 'Working…',
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
    await act(async () => {
      release(json({ ok: true, revoked: 2 }))
    })
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/login')
  })

  it.each([401, 403, 500])(
    'keeps %s failure visible and supports a new confirmed retry',
    async (status) => {
      mutate = async () => json({ detail: 'Synthetic rejection' }, status)
      const { confirm, trigger } = await open()
      fireEvent.click(confirm)
      await screen.findByRole('alert')
      expect(navigate).not.toHaveBeenCalled()
      await waitFor(() =>
        expect((trigger as HTMLButtonElement).disabled).toBe(false)
      )
      mutate = async () => json({ ok: true, revoked: 2 })
      fireEvent.click(trigger)
      fireEvent.click(
        within(await screen.findByRole('alertdialog')).getByRole('button', {
          name: 'Sign out everywhere',
        })
      )
      await waitFor(() =>
        expect(navigate).toHaveBeenCalledExactlyOnceWith('/login')
      )
      expect(writes()).toHaveLength(2)
    }
  )

  it('does not claim success for a network response that may have been lost', async () => {
    mutate = async () => {
      throw new TypeError('network unavailable')
    }
    const { confirm } = await open()
    fireEvent.click(confirm)
    expect((await screen.findByRole('alert')).textContent).toBe(unconfirmed)
    expect(navigate).not.toHaveBeenCalled()
  })

  it.each([
    {},
    { ok: false, revoked: 2 },
    { ok: true, revoked: '2' },
    { ok: true, revoked: -1 },
    { ok: true, revoked: 1.2 },
    null,
    'invalid-json',
  ])('does not accept malformed success %j', async (body) => {
    mutate = async () =>
      body === 'invalid-json' ? new Response('{', { status: 200 }) : json(body)
    const { confirm } = await open()
    fireEvent.click(confirm)
    expect((await screen.findByRole('alert')).textContent).toBe(unconfirmed)
    expect(navigate).not.toHaveBeenCalled()
  })

  it.each([0, 2])(
    'navigates only after a valid acknowledged count %i',
    async (revoked) => {
      mutate = async () => json({ ok: true, revoked })
      const { confirm } = await open()
      expect(navigate).not.toHaveBeenCalled()
      fireEvent.click(confirm)
      await waitFor(() =>
        expect(navigate).toHaveBeenCalledExactlyOnceWith('/login')
      )
    }
  )

  it('offers the action when this is the only current session', async () => {
    sessions = [current]
    await open()
    expect(
      screen.queryByRole('button', {
        name: /Sign out all other devices/,
        hidden: true,
      })
    ).toBeNull()
  })

  it('disables logout-all while the existing revoke-others action is pending', async () => {
    let release!: (response: Response) => void
    mutate = () =>
      new Promise<Response>((resolve) => {
        release = resolve
      })
    render(createElement(SecurityPage))
    const all = (await screen.findByRole('button', {
      name: 'Sign out everywhere',
    })) as HTMLButtonElement
    fireEvent.click(
      screen.getByRole('button', { name: 'Sign out all other devices (1)' })
    )
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Sign out others',
      })
    )
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(all.disabled).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
    await act(async () => {
      release(json({ ok: true, revoked: 1 }))
    })
    await waitFor(() => expect(all.disabled).toBe(false))
    expect(writes()[0][0]).toBe('/api/auth/sessions/revoke-others')
  })

  it('preserves the distinct existing revoke-others request', async () => {
    render(createElement(SecurityPage))
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Sign out all other devices (1)',
      })
    )
    fireEvent.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', {
        name: 'Sign out others',
      })
    )
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0][0]).toBe('/api/auth/sessions/revoke-others')
    expect(navigate).not.toHaveBeenCalled()
  })
})
