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
import DealsPage from '@/app/dashboard/deals/page'

const context = vi.hoisted(() => ({
  user: { id: 42 },
  workspace: { id: 7 },
  loading: false,
  permissions: { can_admin: true, can_edit: true, can_review: true },
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => context }))
const deal = {
  schema_version: 'deals/v1',
  id: 41,
  workspace_id: 7,
  company_name: 'Synthetic Buyer',
  buyer_contact_name: null,
  buyer_contact_email: null,
  deal_value_arr: '9999999999999999.99',
  currency: 'XTS',
  stage: 'evaluation',
  close_date: null,
  expected_close_date: '2026-12-31',
  actual_close_date: null,
  requested_frameworks: [],
  linked_questionnaire_ids: [],
  linked_document_ids: [],
  room_id: null,
  crm_source: null,
  crm_external_id: null,
  owner_user_id: null,
  notes: null,
  created_at: null,
}
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status })
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
let rows: unknown[]
let reads: (init: RequestInit) => Promise<Response>
let mutation: (path: string, init: RequestInit) => Promise<Response>
let writes: Array<{ path: string; init: RequestInit }>
beforeEach(() => {
  context.user = { id: 42 }
  context.workspace = { id: 7 }
  context.loading = false
  context.permissions = { can_admin: true, can_edit: true, can_review: true }
  rows = [deal]
  writes = []
  reads = async () => json({ deals: rows })
  mutation = async () => json(deal)
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    if (init.method === 'POST' || init.method === 'PATCH') {
      writes.push({ path, init })
      return mutation(path, init)
    }
    expect(path).toBe('/api/deals')
    return reads(init)
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function open() {
  const view = render(createElement(DealsPage))
  await screen.findByText('Synthetic Buyer')
  return view
}
function change(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}
function newDeal() {
  fireEvent.click(screen.getByRole('button', { name: 'Create deal' }))
  change('Company name', 'New Buyer')
}
function submit() {
  fireEvent.click(screen.getByRole('button', { name: 'Save deal' }))
}
const key = (index: number) =>
  new Headers(writes[index].init.headers).get('Idempotency-Key')

it('loads a complete list under Strict Mode and keeps exact money', async () => {
  render(createElement(StrictMode, null, createElement(DealsPage)))
  await screen.findByText('9999999999999999.99 XTS')
  expect(screen.queryByText('No deals yet')).toBeNull()
})
it.each([
  {},
  { deals: [deal, { ...deal, stage: 'unknown' }] },
  { deals: [{ ...deal, workspace_id: 8 }] },
])(
  'rejects malformed or foreign lists instead of an empty/partial success: %j',
  async (body) => {
    reads = async () => json(body)
    render(createElement(DealsPage))
    await screen.findByText('The response could not be read. Try again.')
    expect(screen.queryByText('No deals yet')).toBeNull()
    expect(screen.queryByText('Synthetic Buyer')).toBeNull()
  }
)
it('retries a failed list and only then shows acknowledged empty data', async () => {
  reads = async () => json({}, 500)
  render(createElement(DealsPage))
  await screen.findByText('Something went wrong')
  reads = async () => json({ deals: [] })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('No deals yet')
})
it('allows session readers without edit/review permissions and hides mutations', async () => {
  context.permissions = { can_admin: false, can_edit: false, can_review: false }
  await open()
  expect(screen.queryByRole('button', { name: 'Create deal' })).toBeNull()
  expect(screen.queryByRole('button', { name: /Edit/ })).toBeNull()
})
it('sends exact decimal strings and explicit currency, then reloads authoritative data', async () => {
  await open()
  newDeal()
  change('ARR amount', '9999999999999999.99')
  change('Currency code', 'XTS')
  mutation = async (_path, init) => {
    rows = [{ ...deal, company_name: 'Server Buyer' }]
    return json({
      ...deal,
      company_name: JSON.parse(String(init.body)).company_name,
    })
  }
  submit()
  await screen.findByText('Server Buyer')
  expect(JSON.parse(String(writes[0].init.body))).toMatchObject({
    deal_value_arr: '9999999999999999.99',
    currency: 'XTS',
  })
  expect(await screen.findByText('Deal saved.')).toBeTruthy()
})
it.each(['1e6', '-1', '01.00', '1.001', '10000000000000000.00'])(
  'rejects invalid decimal input without sending %s',
  async (amount) => {
    await open()
    newDeal()
    change('ARR amount', amount)
    change('Currency code', 'XTS')
    submit()
    await screen.findByText(/Use a non-negative decimal/)
    expect(writes).toHaveLength(0)
  }
)
it('requires explicit currency and never supplies a default', async () => {
  await open()
  newDeal()
  change('ARR amount', '100.01')
  submit()
  await screen.findByText('Enter a currency code for this amount.')
  expect(
    (screen.getByLabelText('Currency code') as HTMLInputElement).value
  ).toBe('')
  expect(writes).toHaveLength(0)
})
it.each([403, 404, 409, 422, 500])(
  'retains entered values after a rejected mutation (%s)',
  async (status) => {
    await open()
    newDeal()
    mutation = async () => json({ detail: 'Synthetic rejection' }, status)
    submit()
    await screen.findByText(
      status === 403 ? /This account cannot complete/ : 'Synthetic rejection'
    )
    expect(
      (screen.getByLabelText('Company name') as HTMLInputElement).value
    ).toBe('New Buyer')
    expect(screen.queryByText('Deal saved.')).toBeNull()
  }
)
it('guards synchronous double submit and retains an uncertain operation key until payload changes', async () => {
  await open()
  newDeal()
  const pending = deferred<Response>()
  mutation = () => pending.promise
  const form = screen
    .getByRole('button', { name: 'Save deal' })
    .closest('form')!
  act(() => {
    fireEvent.submit(form)
    fireEvent.submit(form)
  })
  expect(writes).toHaveLength(1)
  await act(async () => {
    pending.resolve(json({}, 500))
  })
  mutation = async () => {
    throw new Error('network')
  }
  submit()
  await screen.findByText(/could not confirm whether/)
  expect(key(1)).toBe(key(0))
  expect(key(0)).toBeTruthy()
  change('Company name', 'Changed Buyer')
  submit()
  await waitFor(() => expect(writes).toHaveLength(3))
  expect(key(2)).not.toBe(key(0))
})
it('does not acknowledge malformed or foreign mutation responses', async () => {
  await open()
  newDeal()
  mutation = async () => json({ ...deal, workspace_id: 8 })
  submit()
  await screen.findByText(/could not confirm whether/)
  expect(screen.queryByText('Deal saved.')).toBeNull()
  expect(screen.getByLabelText('Company name')).toBeTruthy()
})
it('keeps successful save acknowledgment separate from a failed reload', async () => {
  await open()
  newDeal()
  mutation = async () => {
    reads = async () => json({}, 500)
    return json(deal)
  }
  submit()
  await screen.findByText(
    'Deal saved, but the list could not be refreshed. Try again to load it.'
  )
  expect(screen.queryByText('No deals yet')).toBeNull()
  reads = async () => json({ deals: [deal] })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('Synthetic Buyer')
})
it('edits a legacy unknown currency without resending or inventing money', async () => {
  rows = [{ ...deal, currency: null }]
  await open()
  expect(screen.getByText('Currency not recorded')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Edit Synthetic Buyer' }))
  change('Company name', 'Renamed Buyer')
  submit()
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0].path).toBe('/api/deals/41')
  expect(writes[0].init.method).toBe('PATCH')
  expect(JSON.parse(String(writes[0].init.body))).toEqual({
    company_name: 'Renamed Buyer',
  })
})
it.each(['ARR amount', 'Currency code', 'Expected close date'])(
  'blocks unsupported clearing of stored %s',
  async (label) => {
    await open()
    fireEvent.click(
      screen.getByRole('button', { name: 'Edit Synthetic Buyer' })
    )
    change(label, '')
    submit()
    await screen.findByText(/cannot be cleared here/)
    expect(writes).toHaveLength(0)
  }
)
it('retains an unsaved draft until discard is explicitly confirmed', async () => {
  await open()
  newDeal()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  const confirm = screen.getByRole('alertdialog')
  fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  expect(
    (screen.getByLabelText('Company name') as HTMLInputElement).value
  ).toBe('New Buyer')
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Discard changes',
    })
  )
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})
it('ignores a late previous-workspace read', async () => {
  const late = deferred<Response>()
  reads = () => late.promise
  const view = render(createElement(DealsPage))
  context.workspace = { id: 8 }
  reads = async () =>
    json({
      deals: [{ ...deal, workspace_id: 8, company_name: 'Current Buyer' }],
    })
  view.rerender(createElement(DealsPage))
  await screen.findByText('Current Buyer')
  await act(async () => {
    late.resolve(json({ deals: [deal] }))
  })
  expect(screen.queryByText('Synthetic Buyer')).toBeNull()
})
it('ignores a late previous-workspace save and removes the old draft', async () => {
  const view = await open()
  newDeal()
  const late = deferred<Response>()
  mutation = () => late.promise
  submit()
  context.workspace = { id: 8 }
  rows = [{ ...deal, workspace_id: 8, company_name: 'Current Buyer' }]
  view.rerender(createElement(DealsPage))
  await screen.findByText('Current Buyer')
  await act(async () => {
    late.resolve(json(deal))
  })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByText('Deal saved.')).toBeNull()
})

it('treats a rejected first Strict Mode read as stale while the replacement succeeds', async () => {
  let count = 0
  reads = (init) => {
    count += 1
    if (count > 1) return Promise.resolve(json({ deals: [deal] }))
    return new Promise<Response>((_resolve, reject) =>
      init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
    )
  }
  render(createElement(StrictMode, null, createElement(DealsPage)))
  await screen.findByText('Synthetic Buyer')
  expect(screen.queryByText('Offline')).toBeNull()
})
it('rejects a successful PATCH response for a different deal', async () => {
  await open()
  fireEvent.click(screen.getByRole('button', { name: 'Edit Synthetic Buyer' }))
  change('Company name', 'Edited Buyer')
  mutation = async () => json({ ...deal, id: 42 })
  submit()
  await screen.findByText(/could not confirm whether/)
  expect(screen.queryByText('Deal saved.')).toBeNull()
})
it('revoked admin permission removes an in-flight draft and ignores its result', async () => {
  const view = await open()
  newDeal()
  const late = deferred<Response>()
  mutation = () => late.promise
  submit()
  context.permissions = { can_admin: false, can_edit: true, can_review: true }
  view.rerender(createElement(DealsPage))
  await screen.findByText('Synthetic Buyer')
  await act(async () => {
    late.resolve(json(deal))
  })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Create deal' })).toBeNull()
  expect(screen.queryByText('Deal saved.')).toBeNull()
})
it('asks the browser to warn before unloading an unsaved draft', async () => {
  await open()
  newDeal()
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

it('exposes the complete company and contact as the row header name', async () => {
  rows = [
    {
      ...deal,
      buyer_contact_name: 'Synthetic Contact',
      buyer_contact_email: 'buyer@example.com',
    },
  ]
  await open()
  const list = screen.getByRole('region', { name: 'Deals list' })
  const header = within(list).getByRole('rowheader', {
    name: 'Synthetic Buyer Synthetic Contact · buyer@example.com',
  })
  expect(header.textContent).toContain('Synthetic Buyer')
  expect(header.textContent).toContain('Synthetic Contact · buyer@example.com')
  expect(
    within(list).queryByRole('rowheader', {
      name: 'Other Buyer Synthetic Contact · buyer@example.com',
    })
  ).toBeNull()
})
