// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewPage from '@/app/dashboard/review/[id]/page'
import DemoProofPage from '@/app/dashboard/demo-proof/page'
import { Topbar } from '@/components/layout/Topbar'
import { AISettingsProvider } from '@/contexts/AISettingsContext'

const session = vi.hoisted(() => ({ workspaceId: 7 }))

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: '9' }),
  usePathname: () => '/dashboard/review/9',
  useRouter: () => ({ push: () => {}, refresh: () => {} }),
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 42, email: 'reviewer@example.com', display_name: 'Reviewer' },
    workspace: { id: session.workspaceId, name: 'Synthetic workspace' },
    permissions: {
      can_admin: true,
      can_edit: true,
      can_review: true,
      can_export: true,
    },
  }),
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const summary = {
  schema_version: '1',
  status: 'ready',
  commercial_traction: false,
  metrics: [],
  synthetic_placeholders: [],
  unsupported: [],
  partial_failures: [],
}
let mutate: (url: string, init: RequestInit) => Promise<Response>

beforeEach(() => {
  session.workspaceId = 7
  mutate = async () => json({})
  vi.stubGlobal(
    'fetch',
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = String(input)
      if (init.method === 'PATCH' || init.method === 'POST')
        return mutate(url, init)
      if (url.includes('/api/questionnaires/9'))
        return json({
          id: 9,
          filename: 'questions.xlsx',
          questions: [
            {
              id: 3,
              text: 'Describe access reviews.',
              answer: {
                id: 11,
                text: 'Original draft.',
                status: 'draft',
                citations: '[]',
              },
            },
          ],
        })
      if (url.includes('/api/exports/records')) return json({ records: [] })
      if (url.includes('/api/workspaces/current'))
        return json({
          id: session.workspaceId,
          ai_completion_model: 'gpt-4o-mini',
          ai_temperature: 0.35,
        })
      if (url.includes('/unread-count')) return json({ count: 0 })
      if (url.startsWith('/api/demo-proof')) return json(summary)
      throw new Error(`Unexpected read: ${url}`)
    }
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('answer save acknowledgement ordering', () => {
  it.each([200, 403])(
    'ignores an older %s response body while the latest save is pending',
    async (status) => {
      const olderBody = deferred<unknown>()
      const latestResponse = deferred<Response>()
      let writes = 0
      mutate = async () => {
        writes += 1
        if (writes === 1) {
          const response = json({}, status)
          response.json = () => olderBody.promise
          return response
        }
        return latestResponse.promise
      }
      render(createElement(ReviewPage))
      const field = await screen.findByPlaceholderText('Edit draft answer…')
      fireEvent.change(field, { target: { value: 'Older edit.' } })
      fireEvent.blur(field)
      await waitFor(() => expect(writes).toBe(1))
      fireEvent.change(field, { target: { value: 'Latest edit.' } })
      fireEvent.blur(field)
      await waitFor(() => expect(writes).toBe(2))

      await act(async () => {
        olderBody.resolve({ detail: 'Access denied' })
      })
      expect(screen.getByText('Saving', { exact: true })).toBeTruthy()
      expect(screen.queryByText('Saved', { exact: true })).toBeNull()
      expect((field as HTMLTextAreaElement).value).toBe('Latest edit.')
      expect(screen.queryByText('Action not available')).toBeNull()

      await act(async () => {
        latestResponse.resolve(
          json({ id: 11, text: 'Latest edit.', status: 'draft' })
        )
      })
      expect(screen.getByText('Saved', { exact: true })).toBeTruthy()
    }
  )
})

async function openSettings() {
  const element = createElement(
    AISettingsProvider,
    null,
    createElement(Topbar, {
      navOpen: false,
      onToggleNav: () => {},
      menuButtonRef: null,
    })
  )
  const view = render(element)
  fireEvent.click(screen.getByTitle('Account menu'))
  await act(async () => {})
  return { ...view, element }
}

describe('workspace setting confirmation', () => {
  it.each(['gpt-4o', 'precise'])(
    'clears confirmation when a saved setting changes to %s',
    async (value) => {
      await openSettings()
      fireEvent.click(
        screen.getByRole('button', { name: 'Save for workspace' })
      )
      await screen.findByText('Saved', { exact: true })
      const option = screen.getByRole('option', {
        name: value === 'precise' ? 'Precise' : value,
      })
      fireEvent.change(option.parentElement!, { target: { value } })
      expect(screen.queryByText('Saved', { exact: true })).toBeNull()
    }
  )

  it('does not confirm settings edited while the save was pending, even after reverting the edit', async () => {
    const response = deferred<Response>()
    mutate = () => response.promise
    await openSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Save for workspace' }))
    const select = screen.getByRole('option', { name: 'gpt-4o' }).parentElement!
    fireEvent.change(select, { target: { value: 'gpt-4o' } })
    fireEvent.change(select, { target: { value: 'gpt-4o-mini' } })
    await act(async () => {
      response.resolve(json({}))
    })
    expect(screen.queryByText('Saving', { exact: true })).toBeNull()
    expect(screen.queryByText('Saved', { exact: true })).toBeNull()
  })

  it('does not carry confirmation into another workspace', async () => {
    const view = await openSettings()
    fireEvent.click(screen.getByRole('button', { name: 'Save for workspace' }))
    await screen.findByText('Saved', { exact: true })
    session.workspaceId = 8
    view.rerender(
      createElement(
        AISettingsProvider,
        null,
        createElement(Topbar, {
          navOpen: false,
          onToggleNav: () => {},
          menuButtonRef: null,
        })
      )
    )
    expect(screen.queryByText('Saved', { exact: true })).toBeNull()
  })
})

describe('summary confirmation', () => {
  it.each(['Window start (UTC)', 'Window end (UTC)'])(
    'clears confirmation when %s changes',
    async (label) => {
      mutate = async () => json(summary)
      render(createElement(DemoProofPage))
      await act(async () => {})
      fireEvent.click(screen.getByRole('button', { name: 'Save summary' }))
      await screen.findByText('Saved', { exact: true })
      fireEvent.change(screen.getByLabelText(label), {
        target: { value: '2026-01-01T00:00:00Z' },
      })
      await act(async () => {})
      expect(screen.queryByText('Saved', { exact: true })).toBeNull()
    }
  )

  it('does not confirm a different window when the earlier save completes', async () => {
    const response = deferred<Response>()
    mutate = () => response.promise
    render(createElement(DemoProofPage))
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Save summary' }))
    fireEvent.change(screen.getByLabelText('Window start (UTC)'), {
      target: { value: '2026-01-01T00:00:00Z' },
    })
    await act(async () => {
      response.resolve(json(summary))
    })
    expect(screen.queryByText('Saving', { exact: true })).toBeNull()
    expect(screen.queryByText('Saved', { exact: true })).toBeNull()
  })
})
