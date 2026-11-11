// @vitest-environment happy-dom
import { createElement } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MappingDecision } from '@/app/dashboard/compliance-gaps/mapping-decision'
import { Recommendations } from '@/app/dashboard/compliance-gaps/recommendations'
import { mappingSuggestPath } from '@/lib/controlMappingConsumer'

const question = 'How do you review access?'
const suggestion = {
  control_ids: [9],
  confidence: 1,
  has_override: true,
  reason: 'Human override takes precedence over confirmation and proposal.',
  state: 'overridden',
  version: 3,
  precedence: 3,
  rationale: 'Use the reviewed control.',
  reviewed_by_user_id: 4,
  reviewed_at: '2026-11-11T10:05:00',
}
const held = {
  id: 15,
  question_hash: 'abc123',
  control_ids: [9],
  state: 'overridden',
  version: 3,
  rationale: 'Use the reviewed control.',
  precedence: 3,
  reviewed_by_user_id: 4,
  reviewed_at: '2026-11-11T10:05:00',
  updated: false,
  precedence_held: true,
}
const questionnaire = {
  id: 21,
  filename: 'Customer questionnaire',
  questions: [{ id: 31, text: question, section: 'Access management' }],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('keeps an override on screen after confirm and after a fresh mount', async () => {
  const calls: Array<{ url: string; init: RequestInit }> = []
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(url), init })
    if (init.method === 'POST') return Promise.resolve(json(held))
    return Promise.resolve(json(suggestion))
  })
  const view = render(
    createElement(MappingDecision, { question, canAdmin: true })
  )
  expect(await screen.findByText('Overridden')).toBeTruthy()
  expect(screen.getByText('Use the reviewed control.')).toBeTruthy()
  expect(screen.getAllByText('3').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'Confirm mapping' }))
  expect(await screen.findByText(/This mapping stays overridden/)).toBeTruthy()
  expect(screen.getByText('Overridden')).toBeTruthy()
  expect(screen.queryByText('Confirmed')).toBeNull()
  const confirm = calls.find((call) => call.init.method === 'POST')
  expect(confirm?.url).toBe('/api/compliance/control-mappings/confirm')
  expect(JSON.parse(String(confirm?.init.body))).toEqual({
    question,
    control_ids: [9],
  })
  expect(new Headers(confirm?.init.headers).get('Idempotency-Key')).toBeTruthy()
  view.unmount()
  render(createElement(MappingDecision, { question, canAdmin: true }))
  expect(await screen.findByText('Overridden')).toBeTruthy()
  expect(screen.getByText('Use the reviewed control.')).toBeTruthy()
  expect(screen.queryByText('Confirmed')).toBeNull()
  const reads = calls.filter((call) => call.init.method === undefined)
  expect(reads.map((call) => call.url)).toEqual([
    mappingSuggestPath(question),
    mappingSuggestPath(question),
  ])
})

it('offers confirm, override, and rollback only to an administrator', async () => {
  vi.stubGlobal('fetch', () => Promise.resolve(json(suggestion)))
  const reviewer = render(
    createElement(MappingDecision, { question, canAdmin: false })
  )
  expect(await screen.findByText('Overridden')).toBeTruthy()
  expect(
    screen.getByText(
      'An administrator can confirm, override, or roll back this mapping.'
    )
  ).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Confirm mapping' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Save override' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Roll back mapping' })).toBeNull()
  reviewer.unmount()

  vi.stubGlobal('fetch', () =>
    Promise.resolve(
      json({
        ...suggestion,
        state: 'proposed',
        has_override: false,
        precedence: 1,
        version: null,
        rationale: null,
        confidence: 0.5,
      })
    )
  )
  render(createElement(MappingDecision, { question, canAdmin: true }))
  expect(await screen.findByText('Proposed')).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Confirm mapping' })).toBeTruthy()
  const override = screen.getByRole('button', { name: 'Save override' })
  expect(override.hasAttribute('disabled')).toBe(true)
  expect(screen.queryByRole('button', { name: 'Roll back mapping' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Override rationale'), {
    target: { value: 'Reviewed by hand.' },
  })
  expect(override.hasAttribute('disabled')).toBe(false)
})

it('shows an error instead of a decision when the payload is malformed', async () => {
  vi.stubGlobal('fetch', () => Promise.resolve(json({ state: 'overridden' })))
  render(createElement(MappingDecision, { question, canAdmin: true }))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.queryByText('Overridden')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Confirm mapping' })).toBeNull()
})

it('passes the administrator flag through the question disclosed on coverage', async () => {
  const calls: string[] = []
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push(String(url))
    expect(init.method).toBeUndefined()
    if (String(url).includes('/control-mappings/suggest'))
      return Promise.resolve(json(suggestion))
    return Promise.resolve(json(questionnaire))
  })
  const view = render(
    createElement(Recommendations, {
      recommendations: [
        {
          title: 'Access review record',
          improves_questions: 1,
          evidence_ids: [],
          control_ids: [],
          question_ids: [31],
          question_sources: [{ question_id: 31, questionnaire_id: 21 }],
        },
      ],
      workspaceId: 7,
      canAdmin: false,
    })
  )
  fireEvent.click(
    screen.getByRole('button', { name: 'View question source 1' })
  )
  expect(await screen.findByText(question)).toBeTruthy()
  expect(await screen.findByText('Overridden')).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Confirm mapping' })).toBeNull()
  view.unmount()
  calls.length = 0
  render(
    createElement(Recommendations, {
      recommendations: [
        {
          title: 'Access review record',
          improves_questions: 1,
          evidence_ids: [],
          control_ids: [],
          question_ids: [31],
          question_sources: [{ question_id: 31, questionnaire_id: 21 }],
        },
      ],
      workspaceId: 7,
      canAdmin: true,
    })
  )
  fireEvent.click(
    screen.getByRole('button', { name: 'View question source 1' })
  )
  expect(
    await screen.findByRole('button', { name: 'Confirm mapping' })
  ).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Roll back mapping' })).toBeTruthy()
})
