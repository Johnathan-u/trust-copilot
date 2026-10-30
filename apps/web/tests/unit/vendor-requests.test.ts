// @vitest-environment happy-dom

import { createElement, StrictMode } from 'react'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import RequestsPage from '@/app/dashboard/requests/page'

const context = vi.hoisted(() => ({
  workspace: { id: 7 },
  permissions: { can_edit: true, can_admin: true, can_review: true },
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => context }))

const request = {
  schema_version: '1',
  id: 41,
  workspace_id: 7,
  vendor_email: 'vendor@example.com',
  questionnaire_id: 999,
  message: null,
  status: 'pending',
  link_token: null,
  delivery_status: 'not_sent',
  last_delivery_error: null,
  created_at: '2026-10-01T12:00:00Z',
  expires_at: '2099-01-01T12:00:00Z',
  revoked_at: null,
  last_delivery_at: null,
  submitted_at: null,
}
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
let rows: unknown[]
let reads: (init: RequestInit) => Promise<Response>
let readCalls: string[]
let questionnaires: unknown[]
let mutation: (path: string, init: RequestInit) => Promise<Response>
let writes: Array<{ path: string; init: RequestInit }>
beforeEach(() => {
  context.workspace = { id: 7 }
  context.permissions = { can_edit: true, can_admin: true, can_review: true }
  rows = [request]
  reads = async () => json(rows)
  readCalls = []
  questionnaires = []
  writes = []
  mutation = async () => json(request)
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    if (init.method && init.method !== 'GET') {
      writes.push({ path, init })
      return mutation(path, init)
    }
    readCalls.push(path)
    if (path === '/api/vendor-requests') return reads(init)
    if (path.startsWith('/api/questionnaires?'))
      return Promise.resolve(json(questionnaires))
    throw new Error(`Unexpected URL: ${path}`)
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function open() {
  const view = render(createElement(RequestsPage))
  await screen.findByText('vendor@example.com')
  return view
}
async function create() {
  fireEvent.click(screen.getByRole('button', { name: 'Create Request' }))
  fireEvent.change(screen.getByPlaceholderText('vendor@example.com'), {
    target: { value: 'new@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Create Link' }))
}
const key = (n: number) =>
  new Headers(writes[n].init.headers).get('Idempotency-Key')

it('starts each business read once under Strict Mode effect replay', async () => {
  render(createElement(StrictMode, null, createElement(RequestsPage)))
  await screen.findByText('vendor@example.com')
  expect(readCalls).toEqual([
    '/api/vendor-requests',
    '/api/questionnaires?workspace_id=7',
  ])
})

it('handles the owned pending read rejection when unmounted', async () => {
  let signal: AbortSignal | null | undefined
  reads = (init) => {
    signal = init.signal
    return new Promise<Response>((_resolve, reject) => {
      signal?.addEventListener('abort', () =>
        reject(new DOMException('Read cancelled', 'AbortError'))
      )
    })
  }
  const view = render(createElement(RequestsPage))
  await waitFor(() => expect(signal).toBeDefined())
  await act(async () => view.unmount())
  expect(signal?.aborted).toBe(true)
  // Vitest must observe no unhandled rejection; no global error handler is installed.
  await new Promise((resolve) => setTimeout(resolve, 0))
})

it('keeps a failed requests list as an error when questionnaires load, then retries once', async () => {
  questionnaires = [
    { id: 999, filename: 'Ready questionnaire', status: 'completed' },
  ]
  reads = async () => json({ detail: 'Synthetic failure' }, 500)
  render(createElement(StrictMode, null, createElement(RequestsPage)))
  await screen.findByRole('heading', { name: 'Something went wrong' })
  expect(screen.queryByText('No requests yet')).toBeNull()
  reads = async () => json([request])
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('vendor@example.com')
  expect(
    readCalls.filter((path) => path === '/api/vendor-requests')
  ).toHaveLength(2)
  expect(
    readCalls.filter((path) => path.startsWith('/api/questionnaires?'))
  ).toHaveLength(2)
})

it('allows reviewer reads while withholding administrator mutations', async () => {
  context.permissions = { can_edit: false, can_admin: false, can_review: true }
  await open()
  expect(screen.queryByRole('button', { name: 'Create Request' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Send invitation' })).toBeNull()
  expect(writes).toHaveLength(0)
})

it('does not offer cosmetic completion or expose an unavailable questionnaire id', async () => {
  await open()
  expect(screen.queryByRole('option', { name: 'Completed' })).toBeNull()
  expect(screen.queryByText('#999')).toBeNull()
  expect(screen.getByText('Questionnaire unavailable')).toBeTruthy()
})

it('waits for send acknowledgment and treats acceptance as provider acceptance', async () => {
  const pending = deferred<Response>()
  mutation = () => pending.promise
  await open()
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }))
  expect(writes).toHaveLength(1)
  expect(key(0)).toBeTruthy()
  expect(screen.queryByText('Accepted by email provider')).toBeNull()
  expect(
    screen
      .getByRole('button', { name: 'Send invitation' })
      .hasAttribute('disabled')
  ).toBe(true)
  expect(
    screen
      .getByRole('button', { name: 'Create Request' })
      .hasAttribute('disabled')
  ).toBe(true)
  await act(async () =>
    pending.resolve(
      json({
        ...request,
        delivery_status: 'accepted',
        last_delivery_at: '2026-10-30T10:00:00Z',
      })
    )
  )
  expect(await screen.findByText('Accepted by email provider')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Resend invitation' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Send invitation' })).toBeNull()
})

it.each([
  ['unavailable', 'Email delivery unavailable'],
  ['uncertain', 'Delivery outcome unknown'],
  ['sending', 'Delivery awaiting confirmation'],
  ['unknown', 'No recorded delivery outcome'],
])(
  'renders %s delivery without claiming accepted or delivered',
  async (delivery, label) => {
    rows = [{ ...request, delivery_status: delivery }]
    await open()
    expect(screen.getByText(label)).toBeTruthy()
    expect(screen.queryByText('Accepted by email provider')).toBeNull()
    if (delivery === 'uncertain' || delivery === 'sending') {
      expect(
        screen.queryByRole('button', { name: /send invitation/i })
      ).toBeNull()
      expect(screen.getByText(/Reconcile the previous delivery/)).toBeTruthy()
    }
  }
)

it.each(['Done', 'Close', 'Escape'])(
  'preserves the first one-time invitation across simultaneous rows until %s acknowledgment',
  async (close) => {
    const second = {
      ...request,
      id: 42,
      vendor_email: 'second@example.com',
      delivery_status: 'accepted',
    }
    rows = [request, second]
    const firstResult = deferred<Response>()
    mutation = (path) =>
      path.endsWith('/41/send')
        ? firstResult.promise
        : Promise.resolve(
            json({
              ...second,
              link_token: 'second-token',
              share_url: '/vendor-response?token=second-token',
            })
          )
    await open()
    const send = screen.getByRole('button', { name: 'Send invitation' })
    const resend = screen.getByRole('button', { name: 'Resend invitation' })
    // Native clicks in one React batch exercise the synchronous guard, before
    // disabled props can render. Both same-row and different-row retries race.
    act(() => {
      send.click()
      send.click()
      resend.click()
      resend.click()
    })
    expect(writes).toHaveLength(1)
    expect(resend.hasAttribute('disabled')).toBe(true)
    await act(async () =>
      firstResult.resolve(
        json({
          ...request,
          delivery_status: 'accepted',
          link_token: 'first-token',
          share_url: '/vendor-response?token=first-token',
        })
      )
    )
    const dialog = await screen.findByRole('dialog', {
      name: 'Invitation result',
    })
    expect(dialog.textContent).toContain('first-token')
    expect(resend.hasAttribute('disabled')).toBe(true)
    fireEvent.click(resend)
    expect(writes).toHaveLength(1)
    expect(dialog.textContent).not.toContain('second-token')
    if (close === 'Escape') fireEvent.keyDown(dialog, { key: 'Escape' })
    else fireEvent.click(within(dialog).getByRole('button', { name: close }))
    expect(screen.queryByRole('dialog')).toBeNull()
    const secondRow = screen.getByText('second@example.com').closest('tr')!
    fireEvent.click(
      within(secondRow).getByRole('button', { name: 'Resend invitation' })
    )
    const next = await screen.findByRole('dialog', {
      name: 'Invitation result',
    })
    expect(writes).toHaveLength(2)
    expect(writes[1].path).toBe('/api/vendor-requests/42/resend')
    expect(key(1)).toBeTruthy()
    expect(next.textContent).toContain('second-token')
  }
)

it('serializes creation with row invitations until its one-time result is closed', async () => {
  const created = deferred<Response>()
  mutation = () => created.promise
  await open()
  const send = screen.getByRole('button', { name: 'Send invitation' })
  await create()
  fireEvent.click(send)
  expect(writes).toHaveLength(1)
  expect(send.hasAttribute('disabled')).toBe(true)
  await act(async () =>
    created.resolve(
      json({
        ...request,
        id: 42,
        link_token: 'created-token',
        share_url: '/vendor-response?token=created-token',
      })
    )
  )
  const dialog = await screen.findByRole('dialog', { name: 'Request Created' })
  const invite = screen.getByText('vendor@example.com').closest('tr')!
  const inviteButton = within(invite).getByRole('button', {
    name: 'Send invitation',
    hidden: true,
  })
  expect(inviteButton.hasAttribute('disabled')).toBe(true)
  fireEvent.click(inviteButton)
  expect(writes).toHaveLength(1)
  expect(dialog.textContent).toContain('created-token')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Done' }))
  mutation = async () => json({ ...request, delivery_status: 'accepted' })
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }))
  await screen.findByText('Accepted by email provider')
  expect(writes).toHaveLength(2)
})

it('keeps a send key across an uncertain network result and refresh', async () => {
  mutation = async () => {
    throw new TypeError('offline')
  }
  await open()
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }))
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'Refresh requests' }))
  await screen.findByText('vendor@example.com')
  mutation = async () => json({ ...request, delivery_status: 'accepted' })
  fireEvent.click(screen.getByRole('button', { name: 'Send invitation' }))
  await screen.findByText('Accepted by email provider')
  expect(key(0)).toBeTruthy()
  expect(key(1)).toBe(key(0))
})

it('releases the invitation guard after a rejected row while retaining its retry key', async () => {
  const second = { ...request, id: 42, vendor_email: 'second@example.com' }
  rows = [request, second]
  mutation = async () => json({ detail: 'Retry after reconciliation.' }, 409)
  await open()
  const firstRow = screen.getByText('vendor@example.com').closest('tr')!
  const secondRow = screen.getByText('second@example.com').closest('tr')!
  fireEvent.click(
    within(firstRow).getByRole('button', { name: 'Send invitation' })
  )
  await within(firstRow).findByRole('alert')
  mutation = async () => json({ ...second, delivery_status: 'accepted' })
  fireEvent.click(
    within(secondRow).getByRole('button', { name: 'Send invitation' })
  )
  await within(secondRow).findByText('Accepted by email provider')
  mutation = async () => json({ ...request, delivery_status: 'accepted' })
  fireEvent.click(
    within(firstRow).getByRole('button', { name: 'Send invitation' })
  )
  await within(firstRow).findByText('Accepted by email provider')
  expect(writes.map((write) => write.path)).toEqual([
    '/api/vendor-requests/41/send',
    '/api/vendor-requests/42/send',
    '/api/vendor-requests/41/send',
  ])
  expect(key(0)).toBeTruthy()
  expect(key(2)).toBe(key(0))
  expect(key(1)).not.toBe(key(0))
})

it('retains a rejected progress mutation and displays its 409', async () => {
  mutation = async () =>
    json({ detail: 'This request no longer accepts progress changes.' }, 409)
  await open()
  fireEvent.change(screen.getByRole('combobox', { name: /Update progress/ }), {
    target: { value: 'in_progress' },
  })
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByText('Pending', { exact: true })).toBeTruthy()
  expect(writes[0].path).toBe('/api/vendor-requests/41')
  expect(JSON.parse(String(writes[0].init.body))).toEqual({
    status: 'in_progress',
  })
})

it('does not display creation success before acknowledgment and handles a null-token replay', async () => {
  const pending = deferred<Response>()
  mutation = () => pending.promise
  await open()
  await create()
  expect(screen.queryByText('Request Created')).toBeNull()
  expect(key(0)).toBeTruthy()
  await act(async () =>
    pending.resolve(
      json({ ...request, id: 42, vendor_email: 'new@example.com' })
    )
  )
  const dialog = await screen.findByRole('dialog', { name: 'Request Created' })
  expect(within(dialog).queryByRole('button', { name: 'Copy' })).toBeNull()
  expect(dialog.textContent).not.toContain('undefined')
  expect(
    within(dialog).getByText(/one-time link is not available/i)
  ).toBeTruthy()
})

it('preserves create retry keys across closing and reopening, and replaces them only for changed input', async () => {
  mutation = async () => {
    throw new TypeError('offline')
  }
  await open()
  await create()
  await screen.findByRole('alert')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await create()
  await screen.findByRole('alert')
  expect(key(0)).toBeTruthy()
  expect(key(1)).toBe(key(0))
  fireEvent.change(screen.getByPlaceholderText('vendor@example.com'), {
    target: { value: 'changed@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Create Link' }))
  await screen.findByRole('alert')
  expect(key(2)).toBeTruthy()
  expect(key(2)).not.toBe(key(1))
})

it('does not report success for a malformed successful mutation response', async () => {
  mutation = async () => json({})
  await open()
  await create()
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('Request Created')).toBeNull()
})

it('rejects an off-site one-time link rather than exposing a token to another origin', async () => {
  mutation = async () =>
    json({
      ...request,
      link_token: 'private-token',
      share_url:
        'https://elsewhere.example/vendor-response?token=private-token',
    })
  await open()
  await create()
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('Request Created')).toBeNull()
  expect(document.body.textContent).not.toContain('private-token')
})

it('shows one-time create links without manufacturing them on later list reads', async () => {
  mutation = async () =>
    json({
      ...request,
      id: 42,
      vendor_email: 'new@example.com',
      link_token: 'one-time-token',
      share_url: '/vendor-response?token=one-time-token',
    })
  await open()
  expect(screen.queryByRole('button', { name: 'Copy Link' })).toBeNull()
  await create()
  const dialog = await screen.findByRole('dialog', { name: 'Request Created' })
  expect(
    within(dialog).getByText(/vendor-response\?token=one-time-token/)
  ).toBeTruthy()
})

it('does not apply an old clipboard acknowledgment to a newer one-time link', async () => {
  const copied = deferred<void>()
  vi.stubGlobal('navigator', { clipboard: { writeText: () => copied.promise } })
  mutation = async () =>
    json({
      ...request,
      id: 42,
      link_token: 'first-token',
      share_url: '/vendor-response?token=first-token',
    })
  await open()
  await create()
  const first = await screen.findByRole('dialog', { name: 'Request Created' })
  fireEvent.click(within(first).getByRole('button', { name: 'Copy' }))
  fireEvent.click(within(first).getByRole('button', { name: 'Done' }))
  mutation = async () =>
    json({
      ...request,
      id: 43,
      link_token: 'second-token',
      share_url: '/vendor-response?token=second-token',
    })
  await create()
  await screen.findByRole('dialog', { name: 'Request Created' })
  await act(async () => copied.resolve())
  expect(screen.queryByRole('button', { name: 'Copied!' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Copy' })).toBeTruthy()
})

it('confirms revoke and retains the current row after server rejection', async () => {
  mutation = async () => json({ detail: 'Forbidden' }, 403)
  await open()
  fireEvent.click(screen.getByRole('button', { name: 'Revoke link' }))
  expect(writes).toHaveLength(0)
  const dialog = await screen.findByRole('alertdialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Revoke link' }))
  await screen.findByRole('alert')
  expect(screen.getByText('Pending', { exact: true })).toBeTruthy()
  expect(writes[0].path).toBe('/api/vendor-requests/41/revoke')
})

it.each(['revoked', 'completed'])(
  'shows terminal %s state without invitation or progress actions',
  async (status) => {
    rows = [
      {
        ...request,
        status,
        revoked_at: status === 'revoked' ? '2026-10-30T10:00:00Z' : null,
        submitted_at: status === 'completed' ? '2026-10-30T10:00:00Z' : null,
      },
    ]
    await open()
    expect(
      screen.queryByRole('button', { name: /send invitation/i })
    ).toBeNull()
    expect(
      screen.queryByRole('combobox', { name: /Update progress/ })
    ).toBeNull()
  }
)

it('discards a late list response after switching workspace', async () => {
  const pending = deferred<Response>()
  reads = () => pending.promise
  const view = render(createElement(RequestsPage))
  await waitFor(() =>
    expect(
      readCalls.filter((path) => path === '/api/vendor-requests')
    ).toHaveLength(1)
  )
  context.workspace = { id: 8 }
  reads = async () =>
    json([
      {
        ...request,
        id: 81,
        workspace_id: 8,
        vendor_email: 'current@example.com',
      },
    ])
  view.rerender(createElement(RequestsPage))
  await screen.findByText('current@example.com')
  await act(async () => pending.resolve(json([request])))
  expect(screen.getByText('current@example.com')).toBeTruthy()
  expect(screen.queryByText('vendor@example.com')).toBeNull()
})

it('discards a late create result and its token after switching workspace', async () => {
  const pending = deferred<Response>()
  mutation = () => pending.promise
  const view = await open()
  await create()
  context.workspace = { id: 8 }
  rows = []
  view.rerender(createElement(RequestsPage))
  await screen.findByText('No requests yet')
  const current = deferred<Response>()
  mutation = () => current.promise
  await create()
  expect(writes).toHaveLength(2)
  await act(async () =>
    pending.resolve(
      json({
        ...request,
        link_token: 'foreign-token',
        share_url: '/vendor-response?token=foreign-token',
      })
    )
  )
  expect(screen.queryByText('Request Created')).toBeNull()
  expect(document.body.textContent).not.toContain('foreign-token')
  expect(
    screen.getByRole('button', { name: 'Creating...' }).hasAttribute('disabled')
  ).toBe(true)
  await act(async () =>
    current.resolve(
      json({
        ...request,
        id: 81,
        workspace_id: 8,
        link_token: 'current-token',
        share_url: '/vendor-response?token=current-token',
      })
    )
  )
  const dialog = await screen.findByRole('dialog', { name: 'Request Created' })
  expect(dialog.textContent).toContain('current-token')
  expect(document.body.textContent).not.toContain('foreign-token')
})
