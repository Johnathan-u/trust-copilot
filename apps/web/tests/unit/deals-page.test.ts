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
function riskPayload(overrides: Record<string, unknown> = {}) {
  return {
    deal_id: 41,
    company_name: 'Synthetic Buyer',
    deal_value_arr: '9999999999999999.99',
    stage: 'evaluation',
    risk_score: 0,
    revenue_at_risk: '0.00',
    breakdown: {
      unanswered_questions: 0,
      low_confidence_answers: 0,
      unapproved_answers: 0,
      stale_evidence: 0,
      total_questions: 0,
    },
    ...overrides,
  }
}
function roomPayload(overrides: Record<string, unknown> = {}) {
  return {
    deal_id: 41,
    company_name: 'Synthetic Buyer',
    stage: 'evaluation',
    access_token: 'synthetic-room-marker',
    questionnaires: [],
    trust_center_articles: [],
    summary: { total_questionnaires: 0, total_articles: 0 },
    ...overrides,
  }
}
let rows: unknown[]
let reads: (init: RequestInit) => Promise<Response>
let mutation: (path: string, init: RequestInit) => Promise<Response>
let writes: Array<{ path: string; init: RequestInit }>
let riskStatus: number
let roomStatus: number
let riskResult: unknown
let roomResult: unknown
let detailImpl: ((path: string, init: RequestInit) => Promise<Response>) | null
beforeEach(() => {
  context.user = { id: 42 }
  context.workspace = { id: 7 }
  context.loading = false
  context.permissions = { can_admin: true, can_edit: true, can_review: true }
  rows = [deal]
  writes = []
  riskStatus = 200
  roomStatus = 200
  riskResult = undefined
  roomResult = undefined
  detailImpl = null
  reads = async () => json({ deals: rows })
  mutation = async () => json(deal)
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    if (init.method === 'POST' || init.method === 'PATCH') {
      writes.push({ path, init })
      return mutation(path, init)
    }
    if (path === '/api/deals') return reads(init)
    if (/^\/api\/deals\/\d+\/(risk|room)$/.test(path)) {
      if (detailImpl) return detailImpl(path, init)
      const riskRead = path.endsWith('/risk')
      const status = riskRead ? riskStatus : roomStatus
      const body = riskRead
        ? (riskResult ?? riskPayload())
        : (roomResult ?? roomPayload())
      return json(
        status === 200 ? body : { detail: 'Synthetic read failure' },
        status
      )
    }
    throw new Error(`unexpected ${path}`)
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
async function openLinks(company = 'Synthetic Buyer') {
  fireEvent.click(
    screen.getByRole('button', { name: `Links and risk for ${company}` })
  )
  await screen.findByRole('region', { name: 'Deal links and risk' })
}
function typeQuestionnaire(value: string) {
  fireEvent.change(screen.getByLabelText('Questionnaire id'), {
    target: { value },
  })
}
function linkQuestionnaire() {
  fireEvent.click(screen.getByRole('button', { name: 'Link questionnaire' }))
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

it('lets a reader open links and risk without a link control', async () => {
  context.permissions = { can_admin: false, can_edit: false, can_review: false }
  await open()
  await openLinks()
  expect(await screen.findByText('Risk score')).toBeTruthy()
  expect(
    screen.getByText('No questionnaires are linked to this deal.')
  ).toBeTruthy()
  expect(
    screen.queryByRole('button', { name: 'Link questionnaire' })
  ).toBeNull()
  expect(screen.queryByLabelText('Questionnaire id')).toBeNull()
  expect(screen.queryByText('synthetic-room-marker')).toBeNull()
  expect(writes).toHaveLength(0)
})

it('shows an empty room without inventing revenue', async () => {
  riskResult = riskPayload({ revenue_at_risk: null, deal_value_arr: null })
  await open()
  await openLinks()
  expect(
    await screen.findByText('No questionnaires are linked to this deal.')
  ).toBeTruthy()
  expect(
    screen.getByText('No questionnaires from this workspace are in the room.')
  ).toBeTruthy()
  expect(
    screen.getByText('No published trust center articles are in the room.')
  ).toBeTruthy()
  expect(screen.getByText('Revenue at risk is not recorded')).toBeTruthy()
  expect(screen.queryByText('0.00')).toBeNull()
  expect(screen.queryByText('$0')).toBeNull()
})

it('keeps risk and room loading until those reads resolve', async () => {
  const pending: Array<() => void> = []
  detailImpl = (path) =>
    new Promise((resolve) => {
      pending.push(() =>
        resolve(
          json(
            path.endsWith('/risk')
              ? riskPayload({ company_name: 'Scored Buyer', risk_score: 4 })
              : roomPayload()
          )
        )
      )
    })
  await open()
  fireEvent.click(
    screen.getByRole('button', { name: 'Links and risk for Synthetic Buyer' })
  )
  expect(await screen.findByText('Loading scoped risk…')).toBeTruthy()
  expect(screen.getByText('Loading deal room…')).toBeTruthy()
  expect(screen.queryByText('Scored Buyer')).toBeNull()
  await act(async () => {
    pending.forEach((release) => release())
  })
  expect(await screen.findByText('Scored Buyer')).toBeTruthy()
  expect(screen.queryByText('Loading scoped risk…')).toBeNull()
})

it.each([
  [401, 'Could not load this', 'rejected'],
  [403, 'This section is not available', 'forbidden'],
] as const)(
  'read %s stays distinct from an empty room',
  async (status, title, kind) => {
    riskStatus = status
    roomStatus = status
    await open()
    await openLinks()
    expect(await screen.findAllByText(title)).toHaveLength(2)
    for (const alert of screen.getAllByRole('alert'))
      expect(alert.getAttribute('data-failure')).toBe(kind)
    expect(
      screen.queryByText(
        'No questionnaires from this workspace are in the room.'
      )
    ).toBeNull()
    expect(screen.queryByText('Risk score')).toBeNull()
    expect(
      screen.getByText('No questionnaires are linked to this deal.')
    ).toBeTruthy()
  }
)

it.each([
  [404, 'We could not find that'],
  [500, 'Something went wrong'],
] as const)('read %s does not show a risk score', async (status, title) => {
  riskStatus = status
  roomStatus = status
  await open()
  await openLinks()
  expect(await screen.findAllByText(title)).toHaveLength(2)
  expect(screen.queryByText('Risk score')).toBeNull()
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
})

it('does not show a partial risk score when the risk body is malformed', async () => {
  riskResult = { deal_id: 41, company_name: 'Broken Risk Co' }
  await open()
  await openLinks()
  expect(
    await screen.findByText('The response could not be read. Try again.')
  ).toBeTruthy()
  expect(screen.queryByText('Broken Risk Co')).toBeNull()
  expect(screen.queryByText('Risk score')).toBeNull()
  expect(
    await screen.findByText(
      'No questionnaires from this workspace are in the room.'
    )
  ).toBeTruthy()
})

it('does not show a partial room when one questionnaire is invalid', async () => {
  riskResult = riskPayload({ risk_score: 3 })
  roomResult = roomPayload({
    questionnaires: [
      {
        questionnaire_id: 18,
        name: 'Visible Questionnaire',
        proven: 0,
        pending: 1,
        total: 1,
        questions: [
          {
            question_id: 1,
            text: 'Synthetic question',
            answer_status: 'published',
            answer_text: null,
          },
        ],
      },
    ],
    summary: { total_questionnaires: 1, total_articles: 0 },
  })
  await open()
  await openLinks()
  expect(await screen.findByText('Risk score')).toBeTruthy()
  expect(screen.getByText('3')).toBeTruthy()
  expect(screen.queryByText('Visible Questionnaire')).toBeNull()
  expect(
    screen.getByText('The response could not be read. Try again.')
  ).toBeTruthy()
})

it('does not show risk for a different deal id', async () => {
  riskResult = riskPayload({ deal_id: 99, company_name: 'Other Risk Co' })
  await open()
  await openLinks()
  expect(
    await screen.findByText('The response could not be read. Try again.')
  ).toBeTruthy()
  expect(screen.queryByText('Other Risk Co')).toBeNull()
  expect(screen.queryByText('Risk score')).toBeNull()
})

it('links a questionnaire only after the acknowledgment includes that id', async () => {
  const pending = deferred<Response>()
  mutation = (path) => {
    expect(path).toBe('/api/deals/41/link-questionnaire')
    return pending.promise
  }
  await open()
  await openLinks()
  typeQuestionnaire('18')
  linkQuestionnaire()
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  expect(writes).toHaveLength(1)
  expect(JSON.parse(String(writes[0].init.body))).toEqual({
    questionnaire_id: 18,
  })
  expect(key(0)).toBeTruthy()
  rows = [{ ...deal, linked_questionnaire_ids: [18] }]
  await act(async () => {
    pending.resolve(json(rows[0]))
  })
  expect(await screen.findByText('Questionnaire linked.')).toBeTruthy()
  expect(screen.getByText('Questionnaire 18')).toBeTruthy()
  expect(screen.queryByText('synthetic-room-marker')).toBeNull()
})

it.each([
  ['malformed', {}],
  [
    'foreign workspace',
    { ...deal, workspace_id: 8, linked_questionnaire_ids: [18] },
  ],
  ['different deal', { ...deal, id: 42, linked_questionnaire_ids: [18] }],
  ['missing id', deal],
])('does not acknowledge a %s link response', async (_name, body) => {
  mutation = async () => json(body)
  await open()
  await openLinks()
  typeQuestionnaire('18')
  linkQuestionnaire()
  expect(
    await screen.findByText(
      /could not confirm whether the questionnaire was linked/
    )
  ).toBeTruthy()
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  expect(
    (screen.getByLabelText('Questionnaire id') as HTMLInputElement).value
  ).toBe('18')
})

it('does not keep a link success when the refreshed deal omits the id', async () => {
  mutation = async () => json({ ...deal, linked_questionnaire_ids: [18] })
  await open()
  await openLinks()
  typeQuestionnaire('18')
  linkQuestionnaire()
  expect(
    await screen.findByText(
      'The refreshed deal does not include that questionnaire.'
    )
  ).toBeTruthy()
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  expect(screen.queryByText('Questionnaire 18')).toBeNull()
})

it.each([401, 403, 404, 422, 500])(
  'link %s keeps the id and does not succeed',
  async (status) => {
    mutation = async () => json({ detail: 'Synthetic rejection' }, status)
    await open()
    await openLinks()
    typeQuestionnaire('18')
    linkQuestionnaire()
    expect(
      await screen.findByText(
        status === 403 ? /This account cannot complete/ : 'Synthetic rejection'
      )
    ).toBeTruthy()
    expect(screen.queryByText('Questionnaire linked.')).toBeNull()
    expect(
      (screen.getByLabelText('Questionnaire id') as HTMLInputElement).value
    ).toBe('18')
  }
)

it.each(['', '0', '01', '1.5', '18abc'])(
  'does not send an invalid questionnaire id %j',
  async (value) => {
    await open()
    await openLinks()
    if (value) typeQuestionnaire(value)
    linkQuestionnaire()
    expect(
      await screen.findByText('Enter a positive whole questionnaire id.')
    ).toBeTruthy()
    expect(writes).toHaveLength(0)
    expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  }
)

it('reuses the link key until the questionnaire id changes', async () => {
  await open()
  await openLinks()
  const pending = deferred<Response>()
  mutation = () => pending.promise
  typeQuestionnaire('18')
  const form = screen
    .getByRole('button', { name: 'Link questionnaire' })
    .closest('form')!
  act(() => {
    fireEvent.submit(form)
    fireEvent.submit(form)
  })
  expect(writes).toHaveLength(1)
  await act(async () => {
    pending.resolve(json({ detail: 'Synthetic rejection' }, 500))
  })
  mutation = async () => {
    throw new Error('network')
  }
  linkQuestionnaire()
  expect(
    await screen.findByText(
      /could not confirm whether the questionnaire was linked/
    )
  ).toBeTruthy()
  expect(key(1)).toBe(key(0))
  typeQuestionnaire('19')
  linkQuestionnaire()
  await waitFor(() => expect(writes).toHaveLength(3))
  expect(key(2)).not.toBe(key(0))
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
})

it('ignores a late risk read from the previous workspace', async () => {
  const pending: Array<(value: Response) => void> = []
  detailImpl = () =>
    new Promise((resolve) => {
      pending.push(resolve)
    })
  const view = await open()
  fireEvent.click(
    screen.getByRole('button', { name: 'Links and risk for Synthetic Buyer' })
  )
  expect(await screen.findByText('Loading scoped risk…')).toBeTruthy()
  context.workspace = { id: 8 }
  reads = async () =>
    json({
      deals: [{ ...deal, workspace_id: 8, company_name: 'Current Buyer' }],
    })
  view.rerender(createElement(DealsPage))
  await screen.findByText('Current Buyer')
  await act(async () => {
    for (const resolve of pending)
      resolve(
        json(riskPayload({ company_name: 'Stale Risk Co', risk_score: 9 }))
      )
  })
  expect(screen.queryByText('Stale Risk Co')).toBeNull()
  expect(
    screen.queryByRole('button', { name: 'Links and risk for Synthetic Buyer' })
  ).toBeNull()
})

it('does not apply a late risk read to a different deal', async () => {
  rows = [deal, { ...deal, id: 42, company_name: 'Second Buyer' }]
  const pending: Array<{ path: string; resolve: (value: Response) => void }> =
    []
  detailImpl = (path) =>
    new Promise((resolve) => {
      pending.push({ path, resolve })
    })
  await open()
  fireEvent.click(
    screen.getByRole('button', { name: 'Links and risk for Synthetic Buyer' })
  )
  await screen.findByText('Loading scoped risk…')
  const first = pending.splice(0, pending.length)
  fireEvent.click(
    screen.getByRole('button', { name: 'Links and risk for Second Buyer' })
  )
  await screen.findByRole('heading', {
    name: 'Links and risk for Second Buyer',
  })
  await act(async () => {
    for (const item of first) {
      item.resolve(
        json(
          item.path.endsWith('/risk')
            ? riskPayload({ company_name: 'Stale Risk Co' })
            : roomPayload({
                questionnaires: [
                  {
                    questionnaire_id: 4,
                    name: 'Stale Room Co',
                    proven: 0,
                    pending: 0,
                    total: 0,
                    questions: [],
                  },
                ],
                summary: { total_questionnaires: 1, total_articles: 0 },
              })
        )
      )
    }
  })
  expect(screen.queryByText('Stale Risk Co')).toBeNull()
  expect(screen.queryByText('Stale Room Co')).toBeNull()
  await act(async () => {
    for (const item of pending) {
      item.resolve(
        json(
          item.path.endsWith('/risk')
            ? riskPayload({ deal_id: 42, company_name: 'Current Risk Co' })
            : roomPayload({
                deal_id: 42,
                questionnaires: [
                  {
                    questionnaire_id: 4,
                    name: 'Current Room Co',
                    proven: 0,
                    pending: 0,
                    total: 0,
                    questions: [],
                  },
                ],
                summary: { total_questionnaires: 1, total_articles: 0 },
              })
        )
      )
    }
  })
  expect(await screen.findByText('Current Risk Co')).toBeTruthy()
  expect(screen.getByText('Current Room Co')).toBeTruthy()
  expect(screen.queryByText('Stale Risk Co')).toBeNull()
})

it('ignores a late link acknowledgment from the previous workspace', async () => {
  const pending = deferred<Response>()
  mutation = () => pending.promise
  const view = await open()
  await openLinks()
  typeQuestionnaire('18')
  linkQuestionnaire()
  context.workspace = { id: 8 }
  rows = [{ ...deal, workspace_id: 8, company_name: 'Current Buyer' }]
  view.rerender(createElement(DealsPage))
  await screen.findByText('Current Buyer')
  await act(async () => {
    pending.resolve(json({ ...deal, linked_questionnaire_ids: [18] }))
  })
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  expect(screen.queryByText(/Refreshing the list/)).toBeNull()
})

it('drops an in-flight link when admin permission is removed', async () => {
  const pending = deferred<Response>()
  mutation = () => pending.promise
  const view = await open()
  await openLinks()
  typeQuestionnaire('18')
  linkQuestionnaire()
  context.permissions = { can_admin: false, can_edit: true, can_review: true }
  view.rerender(createElement(DealsPage))
  await screen.findByRole('button', {
    name: 'Links and risk for Synthetic Buyer',
  })
  await act(async () => {
    pending.resolve(json({ ...deal, linked_questionnaire_ids: [18] }))
  })
  expect(screen.queryByText('Questionnaire linked.')).toBeNull()
  expect(screen.queryByLabelText('Questionnaire id')).toBeNull()
})

it('keeps a questionnaire id until discard is confirmed', async () => {
  await open()
  await openLinks()
  typeQuestionnaire('18')
  fireEvent.click(screen.getByRole('button', { name: 'Close links and risk' }))
  const confirm = screen.getByRole('alertdialog')
  expect(confirm.textContent).toContain(
    'The questionnaire id has not been linked.'
  )
  fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  expect(
    (screen.getByLabelText('Questionnaire id') as HTMLInputElement).value
  ).toBe('18')
  fireEvent.click(screen.getByRole('button', { name: 'Close links and risk' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Discard changes',
    })
  )
  await waitFor(() =>
    expect(
      screen.queryByRole('region', { name: 'Deal links and risk' })
    ).toBeNull()
  )
})

it('warns before unloading an unsaved questionnaire id', async () => {
  await open()
  await openLinks()
  typeQuestionnaire('18')
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

it('treats an aborted first risk read as stale while the replacement succeeds', async () => {
  detailImpl = (path, init) =>
    new Promise((resolve, reject) => {
      const succeed = () =>
        resolve(
          json(
            path.endsWith('/risk')
              ? riskPayload({ company_name: 'Scored Buyer' })
              : roomPayload()
          )
        )
      if (init.signal?.aborted) {
        reject(new Error('aborted'))
        return
      }
      init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
      queueMicrotask(() => {
        if (init.signal?.aborted) reject(new Error('aborted'))
        else succeed()
      })
    })
  render(createElement(StrictMode, null, createElement(DealsPage)))
  await screen.findByText('Synthetic Buyer')
  fireEvent.click(
    screen.getByRole('button', { name: 'Links and risk for Synthetic Buyer' })
  )
  expect(await screen.findByText('Scored Buyer')).toBeTruthy()
  expect(screen.queryByText('Offline')).toBeNull()
})
