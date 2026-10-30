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
import { MetadataEditorModal } from '@/components/ui/RegistryListPrimitives'
import QuestionnairesPage from '@/app/dashboard/questionnaires/page'

const context = vi.hoisted(() => ({
  user: { id: 42 },
  workspace: { id: 7 },
  permissions: { can_edit: true },
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => context }))
const row = {
  id: 41,
  display_id: 'QNR-ACK-41',
  filename: 'Acknowledgement questionnaire.xlsx',
  status: 'ready',
  created_at: null,
  deleted_at: '2026-10-01T00:00:00Z',
  frameworks: ['SOC 2'],
  subject_areas: ['Other'],
}
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status })
let mutation: () => Promise<Response>
let writes: RequestInit[]
beforeEach(() => {
  context.workspace = { id: 7 }
  context.user = { id: 42 }
  writes = []
  mutation = async () => json({ detail: 'Permission denied' }, 403)
  vi.stubGlobal(
    'fetch',
    (_input: RequestInfo | URL, init: RequestInit = {}) => {
      if (init.method === 'POST' || init.method === 'PATCH') {
        writes.push(init)
        return mutation()
      }
      return Promise.resolve(json({ items: [row] }))
    }
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function open() {
  const view = render(
    createElement(StrictMode, null, createElement(QuestionnairesPage))
  )
  await screen.findByText(row.filename)
  fireEvent.click(
    screen.getByRole('button', { name: `Actions for ${row.display_id}` })
  )
  return view
}
it('does not report an archived questionnaire restored after a real-shaped 403', async () => {
  await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Restore' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  await screen.findByRole('alert')
  expect(screen.getByText('Archived')).toBeTruthy()
})

function deferred() {
  let resolve!: (value: Response) => void
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
const failures: [string, () => Promise<Response>][] = [
  ['403', async () => json({ detail: 'Permission denied' }, 403)],
  ['404', async () => json({ detail: 'Questionnaire not found' }, 404)],
  ['500', async () => json({ detail: 'Server error' }, 500)],
  ['false acknowledgement', async () => json({ ok: false })],
  ['missing acknowledgement', async () => json({})],
  ['null body', async () => json(null)],
  ['invalid JSON', async () => new Response('invalid')],
  [
    'transport failure',
    async () => {
      throw new TypeError('Failed to fetch')
    },
  ],
]
it.each(failures)(
  'keeps restore state after %s, then accepts a matching acknowledgement',
  async (_name, failure) => {
    mutation = failure
    await open()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Restore' }))
    await screen.findByRole('alert')
    expect(screen.getByText('Archived')).toBeTruthy()
    expect(screen.queryByText('Questionnaire restored.')).toBeNull()
    mutation = async () =>
      json({ ok: true, id: row.id, display_id: row.display_id })
    fireEvent.click(screen.getByRole('button', { name: 'Retry restore' }))
    await screen.findByText('Questionnaire restored.')
    expect(screen.queryByText('Archived')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  }
)
it('rejects a successful restore acknowledgement for a different questionnaire', async () => {
  mutation = async () => json({ ok: true, id: 999 })
  await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Restore' }))
  await screen.findByRole('alert')
  expect(screen.getByText('Archived')).toBeTruthy()
})
it('prevents duplicate restores while awaiting acknowledgement', async () => {
  const pending = deferred()
  mutation = () => pending.promise
  await open()
  const restore = screen.getByRole('menuitem', { name: 'Restore' })
  act(() => {
    fireEvent.click(restore)
    fireEvent.click(restore)
  })
  expect(writes).toHaveLength(1)
  expect(screen.getByText('Restoring…')).toBeTruthy()
  expect(
    screen
      .getByRole('button', { name: `Actions for ${row.display_id}` })
      .closest('fieldset')?.disabled
  ).toBe(true)
  expect(screen.getByText('Archived')).toBeTruthy()
  await act(async () => pending.resolve(json({ ok: true, id: row.id })))
  await screen.findByText('Questionnaire restored.')
})
async function edit() {
  await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Edit metadata' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'ISO 27001' }))
  return dialog
}
it.each(failures)(
  'preserves metadata draft and confirmed registry after %s, then retries',
  async (_name, failure) => {
    mutation = failure
    const dialog = await edit()
    await within(dialog).findByRole('alert')
    expect(
      within(dialog)
        .getByRole('button', { name: 'ISO 27001' })
        .getAttribute('aria-pressed')
    ).toBe('true')
    expect(document.querySelector('[title="framework: ISO 27001"]')).toBeNull()
    expect(document.querySelector('[title="framework: SOC 2"]')).toBeTruthy()
    expect(screen.queryByText('Metadata saved.')).toBeNull()
    mutation = async () => json({ ok: true })
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Retry saving' })
    )
    await screen.findByText('Metadata saved.')
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(
      document.querySelector('[title="framework: ISO 27001"]')
    ).toBeTruthy()
    expect(JSON.parse(String(writes[1].body))).toEqual({
      frameworks: ['SOC 2', 'ISO 27001'],
      subject_areas: ['Other'],
    })
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[1])
    fireEvent.click(
      screen.getByRole('button', { name: `Actions for ${row.display_id}` })
    )
    fireEvent.click(screen.getByRole('menuitem', { name: 'Edit metadata' }))
    expect(
      screen
        .getByRole('button', { name: 'ISO 27001' })
        .getAttribute('aria-pressed')
    ).toBe('true')
  }
)
it('disables chips and close while autosaving without duplicate requests', async () => {
  const pending = deferred()
  mutation = () => pending.promise
  await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Edit metadata' }))
  const dialog = screen.getByRole('dialog')
  const chip = within(dialog).getByRole('button', { name: 'ISO 27001' })
  act(() => {
    fireEvent.click(chip)
    fireEvent.click(chip)
  })
  expect(writes).toHaveLength(1)
  for (const button of within(dialog).getAllByRole('button'))
    expect((button as HTMLButtonElement).disabled).toBe(true)
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(screen.getByRole('dialog')).toBeTruthy()
  await act(async () => pending.resolve(json({ ok: true })))
  await within(dialog).findByText('Metadata saved.')
  expect((chip as HTMLButtonElement).disabled).toBe(false)
})
it('retains prior legacy metadata consumers autosave behaviour', () => {
  const onSave = vi.fn()
  render(
    createElement(MetadataEditorModal, {
      isOpen: true,
      frameworks: ['SOC 2'],
      subjectAreas: [],
      onClose: vi.fn(),
      onSave,
    })
  )
  fireEvent.click(screen.getByRole('button', { name: 'ISO 27001' }))
  expect(onSave).toHaveBeenCalledExactlyOnceWith({
    frameworks: ['SOC 2', 'ISO 27001'],
    subject_areas: [],
  })
  expect(screen.queryByRole('button', { name: 'Retry saving' })).toBeNull()
})
it('does not apply a late restore response to a newly selected workspace', async () => {
  const pending = deferred()
  mutation = () => pending.promise
  const view = await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Restore' }))
  context.workspace = { id: 8 }
  view.rerender(
    createElement(StrictMode, null, createElement(QuestionnairesPage))
  )
  await screen.findByText(row.filename)
  await act(async () => pending.resolve(json({ ok: true, id: row.id })))
  expect(screen.getByText('Archived')).toBeTruthy()
  expect(screen.queryByText('Questionnaire restored.')).toBeNull()
})

it('autosaves successive acknowledged selections without losing earlier choices', async () => {
  mutation = async () => json({ ok: true })
  const dialog = await edit()
  await within(dialog).findByText('Metadata saved.')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Encryption' }))
  await within(dialog).findByText('Metadata saved.')
  fireEvent.click(within(dialog).getByRole('button', { name: 'HIPAA' }))
  await within(dialog).findByText('Metadata saved.')
  expect(writes).toHaveLength(3)
  expect(JSON.parse(String(writes[2].body))).toEqual({
    frameworks: ['SOC 2', 'ISO 27001', 'HIPAA'],
    subject_areas: ['Other', 'Encryption'],
  })
  expect(document.querySelector('[title="framework: ISO 27001"]')).toBeTruthy()
  expect(document.querySelector('[title="topic: Encryption"]')).toBeTruthy()
})
it('does not apply a late metadata acknowledgement to a different current user', async () => {
  const pending = deferred()
  mutation = () => pending.promise
  const view = await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Edit metadata' }))
  fireEvent.click(screen.getByRole('button', { name: 'ISO 27001' }))
  context.user = { id: 43 }
  view.rerender(
    createElement(StrictMode, null, createElement(QuestionnairesPage))
  )
  await screen.findByText(row.filename)
  await act(async () => pending.resolve(json({ ok: true })))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.querySelector('[title="framework: ISO 27001"]')).toBeNull()
  expect(screen.queryByText('Metadata saved.')).toBeNull()
})
it('reflects the API Other fallback after clearing the last label is acknowledged', async () => {
  mutation = async () => json({ ok: true })
  await open()
  fireEvent.click(screen.getByRole('menuitem', { name: 'Edit metadata' }))
  const dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'SOC 2' }))
  await within(dialog).findByText('Metadata saved.')
  expect(JSON.parse(String(writes[0].body)).frameworks).toEqual([])
  expect(
    within(dialog)
      .getAllByRole('button', { name: 'Other' })[0]
      .getAttribute('aria-pressed')
  ).toBe('true')
  fireEvent.click(within(dialog).getByRole('button', { name: 'ISO 27001' }))
  await within(dialog).findByText('Metadata saved.')
  expect(JSON.parse(String(writes[1].body)).frameworks).toEqual([
    'Other',
    'ISO 27001',
  ])
})
