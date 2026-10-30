// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DemoProofPage from '@/app/dashboard/demo-proof/page'

const session = vi.hoisted(() => ({ workspaceId: 7 }))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    workspace: { id: session.workspaceId },
    permissions: { can_edit: true },
  }),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function summary(name: string) {
  return {
    schema_version: '1',
    status: 'ready',
    commercial_traction: false,
    metrics: [
      { name, value: 12, state: 'available', commercial_traction: false },
    ],
    synthetic_placeholders: [],
    unsupported: [],
    partial_failures: [],
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type Change = 'window' | 'workspace'
function changeContext(change: Change, view: ReturnType<typeof render>) {
  if (change === 'window') {
    fireEvent.change(screen.getByLabelText('Window start (UTC)'), {
      target: { value: '2026-01-01T00:00:00Z' },
    })
  } else {
    session.workspaceId = 8
    view.rerender(createElement(DemoProofPage))
  }
}

beforeEach(() => {
  session.workspaceId = 7
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe.each(['window', 'workspace'] as const)(
  'summary requests after a %s change',
  (change) => {
    it.each([
      ['GET', 'success'],
      ['GET', 'http error'],
      ['GET', 'network error'],
      ['POST', 'success'],
      ['POST', 'http error'],
      ['POST', 'network error'],
    ] as const)('ignores an older %s %s', async (method, outcome) => {
      const oldBody = deferred<unknown>()
      const oldNetwork = deferred<Response>()
      const oldResponse = json({}, outcome === 'http error' ? 500 : 200)
      oldResponse.json = () => oldBody.promise
      let oldStarted = false
      vi.stubGlobal('fetch', (_input: unknown, init: RequestInit) => {
        if (!oldStarted && init.method === method) {
          oldStarted = true
          return outcome === 'network error'
            ? oldNetwork.promise
            : Promise.resolve(oldResponse)
        }
        return Promise.resolve(json(summary('Current records')))
      })
      const view = render(createElement(DemoProofPage))
      await act(async () => {})
      if (method === 'POST') {
        fireEvent.click(screen.getByRole('button', { name: 'Save summary' }))
        await act(async () => {})
      }
      changeContext(change, view)
      await screen.findByText('Current records')
      await act(async () => {
        if (outcome === 'network error')
          oldNetwork.reject(new Error('Older request failed'))
        else
          oldBody.resolve(
            outcome === 'http error'
              ? { detail: 'Older request failed' }
              : summary('Older records')
          )
      })
      expect(screen.getByText('Current records')).toBeTruthy()
      expect(screen.queryByText('Older records')).toBeNull()
      expect(screen.queryByRole('alert')).toBeNull()
      expect(screen.queryByText('Saved', { exact: true })).toBeNull()
    })

    it('keeps the current GET loading when an older GET finishes', async () => {
      const old = deferred<Response>()
      const current = deferred<Response>()
      let reads = 0
      vi.stubGlobal('fetch', () =>
        ++reads === 1 ? old.promise : current.promise
      )
      const view = render(createElement(DemoProofPage))
      changeContext(change, view)
      await act(async () => {
        old.resolve(json(summary('Older records')))
      })
      expect(screen.queryByText('Older records')).toBeNull()
      expect(
        (screen.getByRole('button', { name: 'Retry' }) as HTMLButtonElement)
          .disabled
      ).toBe(true)
      await act(async () => {
        current.resolve(json(summary('Current records')))
      })
      expect(screen.getByText('Current records')).toBeTruthy()
      expect(
        (screen.getByRole('button', { name: 'Retry' }) as HTMLButtonElement)
          .disabled
      ).toBe(false)
    })

    it('lets the new context save and ignores the old POST finalizer', async () => {
      const old = deferred<Response>()
      const current = deferred<Response>()
      let writes = 0
      vi.stubGlobal('fetch', (_input: unknown, init: RequestInit) =>
        init.method === 'POST'
          ? ++writes === 1
            ? old.promise
            : current.promise
          : Promise.resolve(json(summary('Current records')))
      )
      const view = render(createElement(DemoProofPage))
      await act(async () => {})
      fireEvent.click(screen.getByRole('button', { name: 'Save summary' }))
      changeContext(change, view)
      await act(async () => {})
      fireEvent.click(screen.getByRole('button', { name: 'Save summary' }))
      await act(async () => {
        old.resolve(json(summary('Older records')))
      })
      expect(screen.getByText('Saving', { exact: true })).toBeTruthy()
      expect(screen.queryByText('Saved', { exact: true })).toBeNull()
      expect(screen.queryByText('Older records')).toBeNull()
      await act(async () => {
        current.resolve(json(summary('Saved current records')))
      })
      expect(screen.getByText('Saved current records')).toBeTruthy()
      expect(screen.getByText('Saved', { exact: true })).toBeTruthy()
    })
  }
)

it.each(['http', 'network'])(
  'shows a current %s failure and allows retry',
  async (kind) => {
    vi.stubGlobal('fetch', () =>
      kind === 'http'
        ? Promise.resolve(json({ detail: 'Current request failed' }, 500))
        : Promise.reject(new Error('Current network failure'))
    )
    render(createElement(DemoProofPage))
    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(
      kind === 'http'
        ? 'Current request failed'
        : 'Network error loading the demonstration summary.'
    )
    expect(
      (screen.getByRole('button', { name: 'Retry' }) as HTMLButtonElement)
        .disabled
    ).toBe(false)
  }
)
