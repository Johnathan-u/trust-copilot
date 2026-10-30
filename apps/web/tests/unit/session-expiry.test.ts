// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'

const me = (remaining = 600) => ({
  id: 1,
  email: 'synthetic@example.com',
  display_name: 'Synthetic',
  workspace_id: 1,
  workspace_name: 'Workspace',
  role: 'reviewer',
  workspaces: [],
  session_expires_at: 2_000_000_000 + remaining,
  server_time: 2_000_000_000,
})
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status })
let fetchMock: ReturnType<typeof vi.fn>
let respond: () => Promise<Response>
let visible: boolean
let switchResult: boolean | undefined

function Probe() {
  const auth = useAuth()
  return createElement(
    'div',
    null,
    createElement('pre', { 'data-testid': 'auth' }, JSON.stringify(auth)),
    createElement('button', { onClick: () => void auth.refresh() }, 'Refresh'),
    createElement(
      'button',
      {
        onClick: () =>
          void auth.switchWorkspace(2).then((result) => {
            switchResult = result
          }),
      },
      'Switch'
    )
  )
}

const state = () => JSON.parse(screen.getByTestId('auth').textContent || '{}')
async function open() {
  const rendered = render(
    createElement(AuthProvider, null, createElement(Probe))
  )
  await act(async () => {})
  return rendered
}
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}
async function visibility(shown: boolean) {
  visible = shown
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: ['Date', 'performance', 'setTimeout', 'clearTimeout'],
  })
  vi.setSystemTime(new Date('2000-01-01T00:00:00Z'))
  visible = true
  switchResult = undefined
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() =>
    visible ? 'visible' : 'hidden'
  )
  respond = async () => json(me())
  fetchMock = vi.fn(() => respond())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('server-confirmed absolute expiry lifecycle', () => {
  it('anchors the server deadline to elapsed time despite a skewed browser clock', async () => {
    await open()
    expect(state().session_expiry).toEqual({
      expires_at: 2_000_000_600,
      deadline: 600_000,
      check_at: 600_000,
    })
    expect(state().session_expiry_status).toBe('ready')
    expect(fetchMock.mock.calls[0][1].cache).toBe('no-store')
  })

  it('deducts request duration instead of claiming that time remains available', async () => {
    let release!: (value: Response) => void
    respond = () => new Promise((resolve) => (release = resolve))
    await open()
    await advance(5_000)
    await act(async () => release(json(me(100))))
    expect(state().session_expiry.deadline).toBe(100_000)
    expect(state().session_expiry.check_at).toBe(105_000)
  })

  it('waits for the latest possible server deadline when response latency exceeds remaining time', async () => {
    let release!: (value: Response) => void
    respond = () => new Promise((resolve) => (release = resolve))
    await open()
    await advance(5_000)
    await act(async () => release(json(me(2))))
    expect(state().session_expiry.deadline).toBe(2_000)
    expect(state().session_expiry.check_at).toBe(7_000)
    respond = async () => json({ detail: 'Session expired' }, 401)
    await advance(1_999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(state().user).toBeNull()
  })

  it('revalidates at the deadline without renewing a cookie or issuing a mutation', async () => {
    respond = async () => json(me(2))
    await open()
    respond = async () => json({ detail: 'Session expired' }, 401)
    await advance(1_999)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(state().user).toBeNull()
    expect(state().session_expiry).toBeNull()
    expect(fetchMock.mock.calls.every(([, init]) => !init.method)).toBe(true)
    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('has no periodic polling and observes shortened policy when a hidden tab returns', async () => {
    await open()
    await advance(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await visibility(false)
    respond = async () => json(me(30))
    await visibility(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(state().session_expiry.deadline).toBe(90_000)
  })

  it('does not fetch while hidden and checks server authority on returning after expiry', async () => {
    respond = async () => json(me(2))
    await open()
    await visibility(false)
    await advance(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    respond = async () => json({ detail: 'Session invalidated' }, 401)
    await visibility(true)
    expect(state().user).toBeNull()
  })

  it('prevents a late successful response from restoring a revoked session', async () => {
    await open()
    let release!: (value: Response) => void
    respond = () => new Promise((resolve) => (release = resolve))
    fireEvent.click(screen.getByText('Refresh'))
    await visibility(false)
    respond = async () => json({ detail: 'Session invalidated' }, 401)
    await visibility(true)
    expect(state().user).toBeNull()
    await act(async () => release(json(me(3_600))))
    expect(state().user).toBeNull()
    expect(state().session_expiry).toBeNull()
  })

  it.each([undefined, null, 'later', -1, Number.NaN])(
    'does not invent a deadline when timing metadata is invalid: %s',
    async (expiry) => {
      respond = async () => json({ ...me(), session_expires_at: expiry })
      await open()
      expect(state().user.id).toBe(1)
      expect(state().session_expiry).toBeNull()
      expect(state().session_expiry_status).toBe('unavailable')
    }
  )

  it('suppresses a precise countdown on network failure without claiming sign-out', async () => {
    await open()
    await visibility(false)
    respond = async () => {
      throw new Error('offline')
    }
    await visibility(true)
    expect(state().user.id).toBe(1)
    expect(state().session_expiry).toBeNull()
    expect(state().session_expiry_status).toBe('unavailable')
  })

  it('loads the newly enforced deadline after workspace switching', async () => {
    await open()
    fetchMock.mockImplementation(async (url: string) =>
      url.endsWith('switch-workspace')
        ? json({ workspace_id: 2, workspace_name: 'Second', role: 'reviewer' })
        : json({ ...me(20), workspace_id: 2, workspace_name: 'Second' })
    )
    await act(async () => fireEvent.click(screen.getByText('Switch')))
    expect(state().workspace.id).toBe(2)
    expect(state().session_expiry.deadline).toBe(20_000)
    expect(switchResult).toBe(true)
  })

  it('withholds old workspace authority until an acknowledged switch is confirmed', async () => {
    respond = async () =>
      json({
        ...me(),
        permissions: {
          can_edit: true,
          can_review: true,
          can_admin: true,
          can_export: true,
        },
      })
    await open()
    let release!: (value: Response) => void
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('switch-workspace')
        ? Promise.resolve(json({ workspace_id: 2 }))
        : new Promise<Response>((resolve) => (release = resolve))
    )
    await act(async () => fireEvent.click(screen.getByText('Switch')))
    expect(state().user).toBeNull()
    expect(state().workspace).toBeNull()
    expect(state().workspaces).toEqual([])
    expect(state().permissions).toEqual({
      can_edit: false,
      can_review: false,
      can_admin: false,
      can_export: false,
    })
    expect(state().loading).toBe(true)
    expect(state().session_expiry).toBeNull()
    expect(switchResult).toBeUndefined()
    await act(async () => release(json({ ...me(20), workspace_id: 2 })))
    expect(state().workspace.id).toBe(2)
    expect(state().loading).toBe(false)
    expect(switchResult).toBe(true)
  })

  it.each([
    ['network failure', () => Promise.reject(new Error('offline'))],
    ['unauthorized', async () => json({ detail: 'Session expired' }, 401)],
    ['forbidden', async () => json({ detail: 'Not a member' }, 403)],
    ['server failure', async () => json({ detail: 'Unavailable' }, 503)],
    ['invalid JSON', async () => new Response('invalid json')],
    ['null body', async () => json(null)],
    ['missing principal', async () => json({ workspace_id: 2 })],
    ['previous workspace', async () => json(me())],
  ])(
    'does not confirm or restore the old workspace after %s following a switch acknowledgement',
    async (_name, confirmation) => {
      await open()
      fetchMock.mockImplementation((url: string) =>
        url.endsWith('switch-workspace')
          ? Promise.resolve(json({ workspace_id: 2 }))
          : confirmation()
      )
      await act(async () => fireEvent.click(screen.getByText('Switch')))
      expect(state().user).toBeNull()
      expect(state().workspace).toBeNull()
      expect(state().loading).toBe(false)
      expect(state().session_expiry).toBeNull()
      expect(state().session_expiry_status).toBe('unavailable')
      expect(switchResult).toBe(false)
    }
  )

  it('ignores a late pre-switch check after the acknowledged switch cannot be confirmed', async () => {
    await open()
    let release!: (value: Response) => void
    respond = () => new Promise((resolve) => (release = resolve))
    await visibility(false)
    await visibility(true)
    const oldSignal = fetchMock.mock.calls[1][1].signal as AbortSignal
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('switch-workspace')
        ? Promise.resolve(json({ workspace_id: 2 }))
        : Promise.reject(new Error('offline'))
    )
    await act(async () => fireEvent.click(screen.getByText('Switch')))
    expect(oldSignal.aborted).toBe(true)
    await act(async () => release(json(me(3_600))))
    expect(state().user).toBeNull()
    expect(state().workspace).toBeNull()
    expect(state().session_expiry).toBeNull()
    expect(switchResult).toBe(false)
  })

  it('requires the switched workspace when a visibility refresh supersedes confirmation', async () => {
    await open()
    let release!: (value: Response) => void
    fetchMock.mockImplementation((url: string) =>
      url.endsWith('switch-workspace')
        ? Promise.resolve(json({ workspace_id: 2 }))
        : new Promise<Response>((resolve) => (release = resolve))
    )
    await act(async () => fireEvent.click(screen.getByText('Switch')))
    await visibility(false)
    fetchMock.mockImplementation(async () => json(me(3_600)))
    await visibility(true)
    expect(state().workspace).toBeNull()
    await act(async () => release(json({ ...me(20), workspace_id: 2 })))
    expect(state().user).toBeNull()
    expect(state().workspace).toBeNull()
    expect(state().session_expiry).toBeNull()
    expect(switchResult).toBe(false)

    fetchMock.mockImplementation(async () =>
      json({ ...me(30), workspace_id: 2 })
    )
    await act(async () => fireEvent.click(screen.getByText('Refresh')))
    expect(state().workspace.id).toBe(2)
    expect(state().session_expiry.deadline).toBe(30_000)
  })

  it('retains an in-flight session check when a workspace switch is rejected', async () => {
    await open()
    let release!: (value: Response) => void
    respond = () => new Promise((resolve) => (release = resolve))
    await visibility(false)
    await visibility(true)
    fetchMock.mockImplementation(async () =>
      json({ detail: 'Not a member' }, 403)
    )
    await act(async () => fireEvent.click(screen.getByText('Switch')))
    await act(async () => release(json(me(100))))
    expect(state().workspace.id).toBe(1)
    expect(state().session_expiry_status).toBe('ready')
    expect(state().session_expiry.deadline).toBe(100_000)
  })

  it('cleans up its deadline, visibility listener and outstanding request on unmount', async () => {
    const rendered = await open()
    rendered.unmount()
    await advance(900_000)
    await visibility(false)
    await visibility(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('aborts an outstanding check when its provider unmounts', async () => {
    respond = () => new Promise(() => {})
    const view = await open()
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal
    expect(signal.aborted).toBe(false)
    view.unmount()
    expect(signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('revalidates when a successful server response arrives after its own deadline', async () => {
    let checks = 0
    respond = async () =>
      ++checks === 1 ? json(me(-1)) : json({ detail: 'Session expired' }, 401)
    await open()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(state().user).toBeNull()
  })

  it('does not overflow the browser timer for a long permitted lifetime', async () => {
    respond = async () => json(me(90 * 86400))
    await open()
    await advance(1_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
