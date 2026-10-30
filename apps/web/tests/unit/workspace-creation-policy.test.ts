// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkspaceCreationPolicy } from '@/components/useWorkspaceCreationPolicy'
import {
  WORKSPACE_CREATION_POLICY_PATH,
  parseWorkspaceCreationPolicy,
  readWorkspaceCreationPolicy,
  resetWorkspaceCreationPolicyForTests,
} from '@/lib/workspace-creation-policy'

const SENTINEL = 'HIDDEN_CAP_VALUE'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function Probe() {
  const { phase, retry } = useWorkspaceCreationPolicy()
  return createElement(
    'div',
    null,
    createElement('p', { 'data-testid': 'phase' }, phase),
    createElement(
      'button',
      { type: 'button', onClick: () => retry() },
      'Try again'
    )
  )
}

describe('parseWorkspaceCreationPolicy', () => {
  it('accepts only an exact boolean', () => {
    expect(
      parseWorkspaceCreationPolicy(200, { can_create_workspace: true })
    ).toBe('allowed')
    expect(
      parseWorkspaceCreationPolicy(200, { can_create_workspace: false })
    ).toBe('denied')
  })

  it('fails closed for any other status or shape', () => {
    const bodies = [
      null,
      undefined,
      'true',
      1,
      [],
      {},
      { can_create_workspace: 'true' },
      { can_create_workspace: 1 },
      { can_create_workspace: true, admin_cap: SENTINEL },
      { can_create_workspace: false, per_hour: 10 },
    ]
    for (const body of bodies) {
      expect(parseWorkspaceCreationPolicy(200, body)).toBe('unavailable')
    }
    expect(
      parseWorkspaceCreationPolicy(401, { can_create_workspace: true })
    ).toBe('unavailable')
    expect(
      parseWorkspaceCreationPolicy(500, { can_create_workspace: false })
    ).toBe('unavailable')
  })
})

describe('readWorkspaceCreationPolicy', () => {
  it('requests the policy path and returns only a phase', async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      jsonResponse({ can_create_workspace: false })
    )
    const phase = await readWorkspaceCreationPolicy(fetchImpl)
    expect(phase).toBe('denied')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe(WORKSPACE_CREATION_POLICY_PATH)
    expect(init).toMatchObject({ method: 'GET', credentials: 'include' })
    expect(init?.body).toBeUndefined()
  })

  it('fails closed on a network error, a bad status, and a non-json body', async () => {
    await expect(
      readWorkspaceCreationPolicy(async () => {
        throw new Error(SENTINEL)
      })
    ).resolves.toBe('unavailable')
    await expect(
      readWorkspaceCreationPolicy(async () =>
        jsonResponse({ detail: SENTINEL }, 503)
      )
    ).resolves.toBe('unavailable')
    await expect(
      readWorkspaceCreationPolicy(
        async () => new Response('not-json', { status: 200 })
      )
    ).resolves.toBe('unavailable')
  })
})

describe('useWorkspaceCreationPolicy', () => {
  const pending: Array<(value: Response | PromiseLike<Response>) => void> = []
  const fetchMock = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        pending.push(resolve)
      })
  )

  beforeEach(() => {
    pending.length = 0
    fetchMock.mockClear()
    resetWorkspaceCreationPolicyForTests()
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'log').mockImplementation(() => {})
    vi.spyOn(console, 'info').mockImplementation(() => {})
    vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    resetWorkspaceCreationPolicyForTests()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function loggedText() {
    return ['log', 'info', 'debug', 'warn', 'error']
      .flatMap((method) => {
        const spy = console[method as 'log'] as unknown as {
          mock?: { calls: unknown[][] }
        }
        return (spy.mock?.calls ?? []).map((call) => call.map(String).join(' '))
      })
      .join('\n')
  }

  it('stays on loading until the read settles', async () => {
    render(createElement(Probe))
    expect(screen.getByTestId('phase').textContent).toBe('loading')
    await waitFor(() => expect(pending).toHaveLength(1))

    pending[0](
      jsonResponse({ can_create_workspace: true, admin_cap: SENTINEL })
    )
    await waitFor(() =>
      expect(screen.getByTestId('phase').textContent).toBe('unavailable')
    )
    expect(document.body.textContent).not.toContain(SENTINEL)
    expect(loggedText()).not.toContain(SENTINEL)

    cleanup()
    resetWorkspaceCreationPolicyForTests()
    pending.length = 0
    render(createElement(Probe))
    await waitFor(() => expect(pending).toHaveLength(1))
    pending[0](jsonResponse({ can_create_workspace: true }))
    await waitFor(() =>
      expect(screen.getByTestId('phase').textContent).toBe('allowed')
    )
  })

  it('shares one read and ignores a stale response after retry', async () => {
    render(createElement(Probe))
    render(createElement(Probe))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getAllByRole('button', { name: 'Try again' })[0])
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(screen.getAllByTestId('phase')[0].textContent).toBe('loading')

    pending[0](jsonResponse({ can_create_workspace: true }))
    await waitFor(() =>
      expect(screen.getAllByTestId('phase')[0].textContent).toBe('loading')
    )

    pending[1](jsonResponse({ can_create_workspace: false }))
    await waitFor(() =>
      expect(screen.getAllByTestId('phase')[0].textContent).toBe('denied')
    )
    expect(screen.getAllByTestId('phase')[1].textContent).toBe('denied')
    expect(document.body.textContent).not.toContain(SENTINEL)
    expect(loggedText()).not.toContain(SENTINEL)
  })

  it('fails closed when the read rejects and retry can ask again', async () => {
    fetchMock.mockImplementationOnce(async () => {
      throw new Error(SENTINEL)
    })
    render(createElement(Probe))
    await waitFor(() =>
      expect(screen.getByTestId('phase').textContent).toBe('unavailable')
    )
    expect(loggedText()).not.toContain(SENTINEL)

    fetchMock.mockImplementationOnce(async () =>
      jsonResponse({ can_create_workspace: false })
    )
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() =>
      expect(screen.getByTestId('phase').textContent).toBe('denied')
    )
  })
})
