// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import VendorResponsePage from '@/app/vendor-response/page'

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams('token=grant-token-value'),
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => navigation.params,
}))

const GENERIC_LINK_ERROR = 'This link is invalid or has expired.'
const pending = {
  status: 'pending',
  message: 'Please reply.',
  questionnaire: null,
}
const receipt = {
  status: 'completed',
  submitted_at: '2026-11-11T12:00:00+00:00',
  response_digest: 'abc',
}

let reads: Response
let submits: Array<(init: RequestInit) => Promise<Response>>
const calls: Array<{ url: string; init: RequestInit }> = []

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  navigation.params = new URLSearchParams('token=grant-token-value')
  reads = json(pending)
  submits = []
  calls.length = 0
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.startsWith('/api/vendor-response?')) return Promise.resolve(reads)
    if (url === '/api/vendor-response/submit') {
      const next = submits.shift()
      if (!next) return Promise.reject(new Error('unexpected submit'))
      return next(init)
    }
    return Promise.reject(new Error(`unexpected ${url}`))
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openPending() {
  render(createElement(VendorResponsePage))
  await screen.findByRole('heading', { name: 'Vendor Request' })
}

function postedBody(index = 0) {
  return JSON.parse(
    String(
      calls.filter((call) => call.url === '/api/vendor-response/submit')[index]
        .init.body
    )
  )
}

it('submits the grant token and the final response', async () => {
  submits = [async () => json(receipt)]
  await openPending()
  expect(
    screen.queryByRole('heading', { name: 'Request Completed' })
  ).toBeNull()
  expect(screen.queryByText(/Coming Soon/i)).toBeNull()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: 'Synthetic final vendor response' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect(
    await screen.findByRole('heading', { name: 'Request Completed' })
  ).toBeTruthy()
  expect(postedBody()).toEqual({
    token: 'grant-token-value',
    response: 'Synthetic final vendor response',
  })
  expect(screen.queryByLabelText('Final response')).toBeNull()
})

it('does not present completion before the submit response', async () => {
  let release: (value: Response) => void = () => {}
  submits = [
    () =>
      new Promise<Response>((resolve) => {
        release = resolve
      }),
  ]
  await openPending()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: 'Still waiting' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect(
    screen.queryByRole('heading', { name: 'Request Completed' })
  ).toBeNull()
  expect(screen.getByRole('button', { name: 'Submitting...' })).toBeTruthy()
  release(json(receipt))
  expect(
    await screen.findByRole('heading', { name: 'Request Completed' })
  ).toBeTruthy()
})

it('keeps a second click from sending another request, then accepts the original receipt', async () => {
  let release: (value: Response) => void = () => {}
  submits = [
    () =>
      new Promise<Response>((resolve) => {
        release = resolve
      }),
  ]
  await openPending()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: 'One response' },
  })
  const button = screen.getByRole('button', { name: 'Submit response' })
  fireEvent.click(button)
  fireEvent.click(button)
  await waitFor(() =>
    expect(
      calls.filter((call) => call.url === '/api/vendor-response/submit')
    ).toHaveLength(1)
  )
  release(json(receipt))
  expect(
    await screen.findByRole('heading', { name: 'Request Completed' })
  ).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('treats an identical retry after a lost response as the completed receipt', async () => {
  submits = [
    async () => Promise.reject(new TypeError('network')),
    async () => json(receipt),
  ]
  await openPending()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: 'Retry the same response' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect((await screen.findByRole('alert')).textContent).toBe(
    'Something went wrong. Please try again later.'
  )
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect(
    await screen.findByRole('heading', { name: 'Request Completed' })
  ).toBeTruthy()
  expect(postedBody(0)).toEqual(postedBody(1))
})

it.each(['revoked', 'expired', 'missing'])(
  'shows one generic message when submit rejects the %s grant',
  async (reason) => {
    submits = [async () => json({ detail: `server said ${reason}` }, 404)]
    await openPending()
    fireEvent.change(screen.getByLabelText('Final response'), {
      target: { value: 'A response' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
    expect(
      await screen.findByRole('heading', { name: 'Link Not Found' })
    ).toBeTruthy()
    expect(screen.getByText(GENERIC_LINK_ERROR)).toBeTruthy()
    expect(screen.queryByText(`server said ${reason}`)).toBeNull()
    expect(
      screen.queryByRole('heading', { name: 'Request Completed' })
    ).toBeNull()
  }
)

it('keeps a conflicting retry on the form', async () => {
  submits = [
    async () =>
      json(
        { detail: 'A different final response was already submitted.' },
        409
      ),
  ]
  await openPending()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: 'A different response' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect((await screen.findByRole('alert')).textContent).toBe(
    'A different final response was already submitted.'
  )
  expect(screen.getByLabelText('Final response')).toBeTruthy()
  expect(
    screen.queryByRole('heading', { name: 'Request Completed' })
  ).toBeNull()
})

it('does not submit a blank response', async () => {
  await openPending()
  fireEvent.change(screen.getByLabelText('Final response'), {
    target: { value: '   ' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit response' }))
  expect((await screen.findByRole('alert')).textContent).toBe(
    'Enter a final response.'
  )
  expect(
    calls.filter((call) => call.url === '/api/vendor-response/submit')
  ).toHaveLength(0)
})
