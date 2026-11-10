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
import WorkspaceTrustPage from '@/app/trust/[slug]/page'
import { publicIntakeClientError } from '@/lib/public-trust-intake'

vi.mock('next/navigation', () => ({
  useParams: () => ({ slug: 'acme' }),
}))

const workspace = { id: 7, name: 'Acme', slug: 'acme' }
const calls: Array<{ url: string; init: RequestInit }> = []
let onSubmit: (init: RequestInit) => Promise<Response>

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  calls.length = 0
  onSubmit = async () => json({ id: 9 })
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, init })
    if (url.includes('/api/workspaces/by-slug/'))
      return Promise.resolve(json(workspace))
    if (url.includes('/api/trust-articles')) return Promise.resolve(json([]))
    if (url.includes('/api/trust-requests/submit')) return onSubmit(init)
    return Promise.reject(new Error(`unexpected ${url}`))
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openForm() {
  render(createElement(WorkspaceTrustPage))
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Request trust information from Acme',
    })
  )
  await screen.findByLabelText('Email')
}

function fill(message = 'Please review our questions.') {
  fireEvent.change(screen.getByLabelText('Email'), {
    target: { value: '  buyer@example.com  ' },
  })
  fireEvent.change(screen.getByLabelText('Name'), {
    target: { value: '  Synthetic Buyer  ' },
  })
  fireEvent.change(screen.getByLabelText('Subject'), {
    target: { value: '  Security questions  ' },
  })
  fireEvent.change(screen.getByPlaceholderText('Your message'), {
    target: { value: message },
  })
}

function chooseFile() {
  fireEvent.change(screen.getByLabelText('Choose file'), {
    target: {
      files: [new File(['synthetic'], 'questions.txt', { type: 'text/plain' })],
    },
  })
}

function submits() {
  return calls.filter((call) => call.url.includes('/api/trust-requests/submit'))
}

function keyOf(index: number) {
  return new Headers(submits()[index].init.headers).get('Idempotency-Key')
}

function formValue(index: number, field: string) {
  return (submits()[index].init.body as FormData).get(field)
}

it('reuses one key after a lost response and does not repeat the upload body', async () => {
  let attempts = 0
  onSubmit = async () => {
    attempts += 1
    if (attempts === 1) throw new TypeError('Failed to fetch')
    return json({ id: 9 })
  }
  await openForm()
  fill('  Please review our questions.  ')
  chooseFile()
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  await waitFor(() => expect(submits().length).toBeGreaterThan(0))
  expect(keyOf(0)).toMatch(/^[A-Za-z0-9._:-]{1,255}$/)
  await screen.findByRole('alert')
  expect(screen.getByRole('alert').textContent).toMatch(
    /could not be confirmed/i
  )
  expect(screen.getByRole('alert').textContent).not.toMatch(/\[object Object\]/)
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  await screen.findByText(/has been sent to/)
  expect(submits()).toHaveLength(2)
  expect(keyOf(0)).toMatch(/^[A-Za-z0-9._:-]{1,255}$/)
  expect(keyOf(1)).toBe(keyOf(0))
  expect(submits()[0].init.method).toBe('POST')
  expect(new Headers(submits()[0].init.headers).has('Content-Type')).toBe(false)
  expect(formValue(0, 'requester_email')).toBe('buyer@example.com')
  expect(formValue(0, 'requester_name')).toBe('Synthetic Buyer')
  expect(formValue(0, 'subject')).toBe('Security questions')
  expect(formValue(0, 'message')).toBe('Please review our questions.')
  expect(formValue(0, 'workspace_slug')).toBe('acme')
  expect((formValue(0, 'document') as File).name).toBe('questions.txt')
  expect((formValue(1, 'document') as File).name).toBe('questions.txt')
  expect(formValue(1, 'message')).toBe(formValue(0, 'message'))
})

it('shows a string conflict and uses a new key when the message changes', async () => {
  onSubmit = async () =>
    json(
      { detail: 'This retry key was already used for a different request.' },
      409
    )
  await openForm()
  fill('Please review our questions.')
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert').textContent).toMatch(/different request/)
  fireEvent.change(screen.getByPlaceholderText('Your message'), {
    target: { value: 'A different public request' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  await waitFor(() => expect(submits()).toHaveLength(2))
  expect(keyOf(0)).toMatch(/^[A-Za-z0-9._:-]{1,255}$/)
  expect(keyOf(1)).not.toBe(keyOf(0))
  expect(formValue(1, 'message')).toBe('A different public request')
})

it('renders a validation list as text and does not echo the rejected input', async () => {
  onSubmit = async () =>
    json(
      {
        detail: [
          {
            loc: ['body', 'message'],
            msg: 'Message is required',
            type: 'value_error',
            input: 'UNIQUE-PRIVATE-INPUT',
          },
        ],
      },
      422
    )
  await openForm()
  fill('Please review our questions.')
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  const alert = await screen.findByRole('alert')
  expect(alert.textContent).toMatch(/10,000/)
  expect(alert.textContent).not.toMatch(/UNIQUE-PRIVATE-INPUT/)
  expect(alert.textContent).not.toMatch(/\[object Object\]/)
  expect(alert.textContent).not.toMatch(/value_error/)
})

it('does not submit a blank or oversize message', async () => {
  await openForm()
  expect((screen.getByLabelText('Email') as HTMLInputElement).maxLength).toBe(
    255
  )
  expect((screen.getByLabelText('Name') as HTMLInputElement).maxLength).toBe(
    255
  )
  expect((screen.getByLabelText('Subject') as HTMLInputElement).maxLength).toBe(
    255
  )
  expect(
    (screen.getByPlaceholderText('Your message') as HTMLTextAreaElement)
      .maxLength
  ).toBe(10000)
  fill('   ')
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  expect((await screen.findByRole('alert')).textContent).toMatch(/message/i)
  expect(submits()).toHaveLength(0)
  const message = screen.getByPlaceholderText(
    'Your message'
  ) as HTMLTextAreaElement
  fireEvent.change(message, { target: { value: 'x'.repeat(10001) } })
  expect(message.value).toHaveLength(10000)
  fireEvent.click(screen.getByRole('button', { name: 'Submit to Acme' }))
  await waitFor(() => expect(submits()).toHaveLength(1))
  expect(formValue(0, 'message')).toHaveLength(10000)
})

it('rejects a blank or oversize message before any request', () => {
  const fields = {
    email: 'buyer@example.com',
    name: 'Synthetic Buyer',
    subject: 'Security questions',
    message: 'Please review our questions.',
  }
  expect(publicIntakeClientError({ ...fields, message: '   ' })).toMatch(
    /message/i
  )
  expect(
    publicIntakeClientError({ ...fields, message: 'x'.repeat(10001) })
  ).toMatch(/10,000/)
  expect(publicIntakeClientError({ ...fields, name: 'n'.repeat(256) })).toMatch(
    /255/
  )
  expect(publicIntakeClientError(fields)).toBeNull()
})
