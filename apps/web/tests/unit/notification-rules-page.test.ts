// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import ComplianceAlertsPage from '@/app/dashboard/notifications/page'
import { POLICY_FORM_UNREADABLE_ERROR } from '@/lib/notification-rule-form'

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ permissions: { can_admin: true } }),
}))

const members = {
  members: [
    {
      id: 90,
      user_id: 17,
      email: 'ada.member@example.com',
      display_name: 'Ada Member',
      role: 'editor',
      suspended: false,
    },
    {
      id: 91,
      user_id: 18,
      email: 'paused.member@example.com',
      display_name: 'Paused Member',
      role: 'editor',
      suspended: true,
    },
  ],
}

let policyStatus = 200
let policyBody: unknown = {
  id: 1,
  event_type: 'member.joined',
  enabled: true,
  recipient_type: 'user',
  recipient_value: '17',
}
const posts: Array<{ path: string; body: Record<string, unknown> }> = []

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

beforeEach(() => {
  policyStatus = 200
  policyBody = {
    id: 1,
    event_type: 'member.joined',
    enabled: true,
    recipient_type: 'user',
    recipient_value: '17',
  }
  posts.length = 0
  vi.stubGlobal(
    'fetch',
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = String(input)
      const method = init.method || 'GET'
      if (method === 'POST' && path === '/api/notifications/policies') {
        posts.push({
          path,
          body: JSON.parse(String(init.body)) as Record<string, unknown>,
        })
        return json(policyBody, policyStatus)
      }
      if (path === '/api/members') return json(members)
      if (path === '/api/notifications/channel-preferences') {
        return json({
          schema_version: 1,
          effective: { email: true, slack: true, in_app: false },
          preferences: [],
        })
      }
      if (path.startsWith('/api/notifications/delivery-attempts')) {
        return json({ schema_version: 1, total: 0, page: 1, attempts: [] })
      }
      if (path === '/api/slack/status' || path === '/api/gmail/status') {
        return json({ provider_mode: 'disabled' })
      }
      if (path === '/api/compliance-alerts/active') return json({ alerts: [] })
      if (path === '/api/notifications/event-types') {
        return json({ event_types: ['member.joined'] })
      }
      if (path === '/api/notifications/policies') return json({ policies: [] })
      if (path.startsWith('/api/notifications/log')) {
        return json({ total: 0, page: 1, entries: [] })
      }
      throw new Error(`Unexpected ${method} ${path}`)
    }
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function selectWithOption(name: string) {
  const found = screen
    .getAllByRole('combobox')
    .find((select) => within(select).queryByRole('option', { name }))
  if (!found) throw new Error(`No select has option ${name}`)
  return found
}

async function openRuleForm() {
  render(createElement(ComplianceAlertsPage))
  const add = await screen.findByRole('button', { name: 'Add rule' })
  await waitFor(() => expect((add as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(add)
  return screen.findByRole('heading', { name: 'Add Alert Rule' })
}

async function chooseUserRecipient() {
  await openRuleForm()
  fireEvent.change(selectWithOption('Specific user'), {
    target: { value: 'user' },
  })
  expect(screen.queryByText('User email or ID')).toBeNull()
  expect(screen.queryByPlaceholderText('e.g. user@company.com')).toBeNull()
  const select = await screen.findByRole('combobox', {
    name: 'Workspace member',
  })
  await screen.findByRole('option', { name: 'Ada Member' })
  return select
}

function submitRule() {
  const form = screen.getByRole('button', { name: 'Add Rule' }).closest('form')
  if (!form) throw new Error('Add Rule form missing')
  fireEvent.submit(form)
}

it('stores an active member user id and does not ask for an email', async () => {
  const select = await chooseUserRecipient()
  expect(screen.queryByText('User email or ID')).toBeNull()
  expect(screen.queryByPlaceholderText('e.g. user@company.com')).toBeNull()
  expect(
    screen.getByText(
      "Choose an active workspace member. The rule stores that member's user id."
    )
  ).toBeTruthy()
  expect(
    within(select)
      .getAllByRole('option')
      .map((option) => (option as HTMLOptionElement).value)
  ).toEqual(['', '17'])
  expect(screen.queryByRole('option', { name: 'Paused Member' })).toBeNull()

  fireEvent.change(select, { target: { value: '17' } })
  submitRule()
  await waitFor(() => expect(posts).toHaveLength(1))
  expect(posts[0].body).toEqual({
    event_type: 'member.joined',
    recipient_type: 'user',
    recipient_value: '17',
  })
  expect(posts[0].body.recipient_value).not.toBe('90')
})

it('renders a fixed string when create returns a non-string detail', async () => {
  policyStatus = 422
  policyBody = {
    detail: [
      {
        loc: ['body', 'recipient_value'],
        msg: 'String should have at most 255 characters',
        type: 'string_too_long',
      },
    ],
  }
  const select = await chooseUserRecipient()
  fireEvent.change(select, { target: { value: '17' } })
  submitRule()
  expect(await screen.findByText(POLICY_FORM_UNREADABLE_ERROR)).toBeTruthy()
  expect(document.body.textContent).not.toContain('string_too_long')
  expect(document.body.textContent).not.toContain('[object Object]')
})

it('shows a string API detail and limits the role field to 255 characters', async () => {
  await openRuleForm()
  fireEvent.change(selectWithOption('Specific role'), {
    target: { value: 'role' },
  })
  const input = screen.getByRole('textbox', {
    name: 'Role name',
  }) as HTMLInputElement
  expect(input.maxLength).toBe(255)
  expect(input.placeholder).toBe('e.g. editor')

  cleanup()
  policyStatus = 404
  policyBody = { detail: 'Recipient not found' }
  const select = await chooseUserRecipient()
  fireEvent.change(select, { target: { value: '17' } })
  submitRule()
  expect(await screen.findByText('Recipient not found')).toBeTruthy()
})
