// @vitest-environment happy-dom
import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import TrustRequestsPage from '@/app/dashboard/trust-requests/page'
import {
  deliveryLabel,
  parseTrustNote,
  parseTrustNotes,
  parseTrustRequest,
  parseTrustRequests,
  replyActions,
  trustFailure,
} from '@/lib/trust-request-consumer'

const request = {
  id: 11,
  workspace_id: 7,
  requester_email: 'buyer@example.com',
  requester_name: null,
  subject: 'Security questions',
  message: 'Please review.',
  status: 'new',
  attachment_filename: 'questions.txt',
  created_at: null,
  assignee_id: null,
  attachment_storage_key: 'private-storage-key',
}
// Serialized by the real backend _note_to_dict(TrustRequestNote(...), None),
// using NOTE_TYPE_INTERNAL from app/models/trust_request_note.py; no DB or mock.
const internalNote = {
  id: 31,
  trust_request_id: 11,
  author_id: null,
  note_type: 'internal_note',
  body: 'Synthetic internal review note.',
  body_revision: 1,
  approved_revision: null,
  approved_by: null,
  approved_at: null,
  delivery_status: null,
  delivery_attempts: null,
  delivery_started_at: null,
  delivery_accepted_at: null,
  delivery_error: null,
  created_at: null,
}
const reply = {
  id: 21,
  trust_request_id: 11,
  note_type: 'reply',
  body: 'Reviewed response',
  body_revision: 2,
  approved_revision: 2,
  approved_by: 42,
  approved_at: '2026-10-01T12:00:00Z',
  delivery_status: 'approved',
  created_at: null,
  author_display_name: 'Reviewer',
}

describe('incoming trust request consumer boundaries', () => {
  it('rejects foreign rows and malformed lists instead of showing another workspace', () => {
    expect(parseTrustRequests([request], 7)[0].subject).toBe(
      'Security questions'
    )
    expect(() => parseTrustRequests([request], 8)).toThrow()
    expect(() => parseTrustRequests({ requests: [request] }, 7)).toThrow()
    expect(() => parseTrustRequest({ ...request, id: 0 }, 7)).toThrow()
    expect(parseTrustRequest(request, 7)).not.toHaveProperty(
      'attachment_storage_key'
    )
  })
  it('rejects a mismatched detail or reply identity', () => {
    expect(() => parseTrustRequest(request, 7, 12)).toThrow()
    expect(() => parseTrustNote(reply, 12)).toThrow()
    expect(() => parseTrustNote(reply, 11, 22)).toThrow()
    expect(() => parseTrustNotes([reply, { ...reply }], 11)).toThrow()
  })
  it('requires approval of the exact saved revision before sending', () => {
    expect(replyActions(parseTrustNote(reply, 11))).toEqual({
      edit: true,
      approve: false,
      send: true,
    })
    for (const changed of [
      { approved_revision: 1 },
      { approved_by: null },
      { approved_at: null },
      { approved_at: 'invalid' },
      { body_revision: 0 },
      { delivery_status: 'draft' },
    ]) {
      expect(
        replyActions(parseTrustNote({ ...reply, ...changed }, 11)).send
      ).toBe(false)
    }
  })
  it.each(['accepted', 'sending', 'uncertain', 'unexpected'])(
    'never edits, approves or resends %s',
    (delivery_status) => {
      expect(
        replyActions(parseTrustNote({ ...reply, delivery_status }, 11))
      ).toEqual({ edit: false, approve: false, send: false })
    }
  )
  it('requires a new saved revision for legacy replies; internal notes have no reply actions', () => {
    expect(
      replyActions(
        parseTrustNote(
          {
            ...reply,
            delivery_status: null,
            body_revision: null,
            approved_revision: null,
          },
          11
        )
      )
    ).toEqual({ edit: true, approve: false, send: false })
    expect(replyActions(parseTrustNote(internalNote, 11))).toEqual({
      edit: false,
      approve: false,
      send: false,
    })
  })
  it('distinguishes provider acceptance from delivery and uncertainty from failure', () => {
    expect(deliveryLabel('accepted')).toMatch(/Provider accepted/)
    expect(deliveryLabel('accepted')).toMatch(/not confirmed/)
    expect(deliveryLabel('uncertain')).toMatch(/unknown/)
    expect(deliveryLabel('unavailable')).toMatch(/unavailable/)
    expect(deliveryLabel(null)).toMatch(/Unknown/)
  })
  it('gives fixed recovery copy for denied, missing, stale and unconfirmed operations', () => {
    expect(trustFailure(403)).toMatch(/permission/)
    expect(trustFailure(404)).toMatch(/unavailable/)
    expect(trustFailure(409)).toMatch(/Reload/)
    expect(trustFailure(0)).toMatch(/not confirmed/)
  })
})

let auth = {
  user: { id: 42 },
  workspace: { id: 7 },
  loading: false,
  permissions: { can_review: true },
}
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth }))
let notes: Record<string, unknown>[] = []
let mutationStatus = 200
let sendStatus = 'accepted'
let calls: { path: string; method: string; body: Record<string, unknown> }[] =
  []
let pendingDetail: ((response: Response) => void) | null = null
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
beforeEach(() => {
  auth = {
    user: { id: 42 },
    workspace: { id: 7 },
    loading: false,
    permissions: { can_review: true },
  }
  notes = [
    {
      ...reply,
      body_revision: 1,
      approved_revision: null,
      approved_by: null,
      approved_at: null,
      delivery_status: 'draft',
    },
  ]
  calls = []
  mutationStatus = 200
  sendStatus = 'accepted'
  pendingDetail = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = url.replace('/api/trust-requests', '')
      const method = init.method ?? 'GET'
      const body = init.body ? JSON.parse(String(init.body)) : {}
      calls.push({ path, method, body })
      if (method !== 'GET' && mutationStatus !== 200)
        return json({}, mutationStatus)
      if (path.startsWith('?'))
        return json(auth.workspace.id === 7 ? [request] : [])
      if (path === '/11') return json(request)
      if (path === '/11/notes') return json(notes)
      if (path.endsWith('/approve'))
        notes[0] = {
          ...notes[0],
          approved_revision: body.revision,
          approved_by: 42,
          approved_at: '2026-10-01T12:00:00Z',
          delivery_status: 'approved',
        }
      else if (path.endsWith('/send'))
        notes[0] = { ...notes[0], delivery_status: sendStatus }
      else if (method === 'PATCH')
        notes[0] = {
          ...notes[0],
          body: body.body,
          body_revision: Number(body.revision) + 1,
          approved_revision: null,
          approved_at: null,
          approved_by: null,
          delivery_status: 'draft',
        }
      else if (method === 'POST')
        notes.push({ ...notes[0], id: 22, body: body.body })
      return json(notes.at(-1))
    })
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function openRequest() {
  const result = render(React.createElement(TrustRequestsPage))
  fireEvent.click(
    await screen.findByRole('button', { name: /Security questions/ })
  )
  await screen.findByLabelText('Reply 21 text')
  return result
}
async function review() {
  fireEvent.click(screen.getByLabelText(/I reviewed saved revision/))
}
it('requires explicit review, approval and send; accepted replies cannot be sent twice', async () => {
  await openRequest()
  expect(
    screen.queryByRole('button', { name: 'Send approved reply' })
  ).toBeNull()
  expect(
    (
      screen.getByRole('button', {
        name: 'Approve revision',
      }) as HTMLButtonElement
    ).disabled
  ).toBe(true)
  await review()
  fireEvent.click(screen.getByRole('button', { name: 'Approve revision' }))
  fireEvent.click(
    await screen.findByRole('button', { name: 'Send approved reply' })
  )
  await screen.findByText(/Provider accepted/)
  expect(
    screen.queryByRole('button', { name: 'Send approved reply' })
  ).toBeNull()
  expect(calls.filter((c) => c.path.endsWith('/send'))).toEqual([
    { path: '/11/replies/21/send', method: 'POST', body: { revision: 1 } },
  ])
})
it.each([403, 404, 409])(
  'retains edited text on %s and requires reload before another action',
  async (status) => {
    await openRequest()
    fireEvent.change(screen.getByLabelText('Reply 21 text'), {
      target: { value: 'Unsaved revision' },
    })
    await review()
    mutationStatus = status
    fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }))
    await screen.findByRole('alert')
    expect(
      (screen.getByLabelText('Reply 21 text') as HTMLTextAreaElement).value
    ).toBe('Unsaved revision')
    expect(
      (
        screen.getByRole('button', {
          name: 'Save new revision',
        }) as HTMLButtonElement
      ).disabled
    ).toBe(true)
    mutationStatus = 200
    fireEvent.click(
      screen.getByRole('button', { name: 'Reload saved replies' })
    )
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
    expect(
      (screen.getByLabelText('Reply 21 text') as HTMLTextAreaElement).value
    ).toBe('Unsaved revision')
  }
)
it('editing an approved reply saves a new revision before approval can recur', async () => {
  notes = [{ ...reply }]
  await openRequest()
  fireEvent.change(screen.getByLabelText('Reply 21 text'), {
    target: { value: 'Changed answer' },
  })
  expect(
    (
      screen.getByRole('button', {
        name: 'Send approved reply',
      }) as HTMLButtonElement
    ).disabled
  ).toBe(true)
  await review()
  fireEvent.click(screen.getByRole('button', { name: 'Save new revision' }))
  await screen.findByText(/Draft — approval required/)
  expect(
    screen.queryByRole('button', { name: 'Send approved reply' })
  ).toBeNull()
  expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
    revision: 2,
    body: 'Changed answer',
  })
})
it.each(['uncertain', 'sending', 'unavailable'])(
  'does not blindly resend a %s result',
  async (status) => {
    notes = [{ ...reply }]
    sendStatus = status
    await openRequest()
    fireEvent.click(screen.getByRole('button', { name: 'Send approved reply' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith('/send'))).toHaveLength(1)
    )
    await screen.findByText(deliveryLabel(status))
    const button = screen.queryByRole('button', {
      name: 'Send approved reply',
    }) as HTMLButtonElement | null
    expect(button === null || button.disabled).toBe(true)
  }
)
it('does not request private rows when the current permission is denied', () => {
  auth.permissions.can_review = false
  render(React.createElement(TrustRequestsPage))
  expect(
    screen.getByRole('heading', { name: 'Review access required' })
  ).toBeTruthy()
  expect(calls).toHaveLength(0)
})
it('clears workspace content on switching and ignores a late old detail', async () => {
  const originalFetch = fetch
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) =>
      url === '/api/trust-requests/11'
        ? new Promise<Response>((resolve) => {
            pendingDetail = resolve
          })
        : originalFetch(url, init)
    )
  )
  const view = render(React.createElement(TrustRequestsPage))
  fireEvent.click(
    await screen.findByRole('button', { name: /Security questions/ })
  )
  await waitFor(() => expect(pendingDetail).not.toBeNull())
  auth = { ...auth, workspace: { id: 8 } }
  view.rerender(React.createElement(TrustRequestsPage))
  pendingDetail!(json(request))
  await screen.findByText('No incoming requests')
  expect(screen.queryByText('Please review.')).toBeNull()
  expect(screen.queryByLabelText('Reply 21 text')).toBeNull()
})

it('retains unsaved text when a refreshed saved reply is no longer available', async () => {
  await openRequest()
  fireEvent.change(screen.getByLabelText('Reply 21 text'), {
    target: { value: 'Keep this local text' },
  })
  notes = []
  fireEvent.click(screen.getByRole('button', { name: 'Reload saved replies' }))
  await screen.findByText(/Saved reply is no longer available/)
  expect(
    (screen.getByLabelText('Reply 21 text') as HTMLTextAreaElement).value
  ).toBe('Keep this local text')
  expect(screen.queryByRole('button', { name: 'Save new revision' })).toBeNull()
})

it('retains an unconfirmed new draft and blocks duplicate creation until inspection', async () => {
  await openRequest()
  fireEvent.change(screen.getByLabelText('Reply text', { exact: true }), {
    target: { value: 'Keep this new draft' },
  })
  mutationStatus = 500
  fireEvent.click(screen.getByRole('button', { name: 'Save draft' }))
  await screen.findByRole('alert')
  expect(
    (
      screen.getByLabelText('Reply text', {
        exact: true,
      }) as HTMLTextAreaElement
    ).value
  ).toBe('Keep this new draft')
  expect(
    (
      screen.getByRole('button', {
        name: 'Save draft',
      }) as HTMLButtonElement
    ).disabled
  ).toBe(true)
  expect(calls.filter((c) => c.path === '/11/replies')).toHaveLength(1)
})
it('blocks repeat send after a lost response, then reads authoritative acceptance', async () => {
  notes = [{ ...reply }]
  await openRequest()
  const originalFetch = fetch
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/send')) {
        notes[0] = { ...notes[0], delivery_status: 'accepted' }
        throw new TypeError('Synthetic lost response')
      }
      return originalFetch(url, init)
    })
  )
  fireEvent.click(screen.getByRole('button', { name: 'Send approved reply' }))
  await screen.findByRole('alert')
  expect(
    (
      screen.getByRole('button', {
        name: 'Send approved reply',
      }) as HTMLButtonElement
    ).disabled
  ).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Reload saved replies' }))
  await screen.findByText(/Provider accepted/)
  expect(
    screen.queryByRole('button', { name: 'Send approved reply' })
  ).toBeNull()
})
it('warns before abandoning a local draft', async () => {
  await openRequest()
  fireEvent.change(screen.getByLabelText('Reply text', { exact: true }), {
    target: { value: 'Unsaved text' },
  })
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

it('accepts the backend internal_note schema alongside a reply without disabling review', async () => {
  expect(parseTrustNotes([internalNote, reply], 11)).toHaveLength(2)
  expect(() =>
    parseTrustNote({ ...internalNote, note_type: 'internal' }, 11)
  ).toThrow()
  notes.push(internalNote)
  await openRequest()
  expect(screen.getByRole('heading', { name: 'Internal note' })).toBeTruthy()
  expect(screen.getByText('Synthetic internal review note.')).toBeTruthy()
  expect(screen.queryByLabelText('Reply 31 text')).toBeNull()
  expect(screen.getByRole('button', { name: 'Approve revision' })).toBeTruthy()
})
