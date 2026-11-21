// @vitest-environment happy-dom

import { createElement } from 'react'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ReviewPage from '@/app/dashboard/review/[id]/page'

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: '9' }),
  usePathname: () => '/dashboard/review/9',
  useRouter: () => ({ push: () => {}, refresh: () => {} }),
}))
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 42, email: 'reviewer@example.com', display_name: 'Reviewer' },
    workspace: { id: 7, name: 'Synthetic workspace' },
    permissions: {
      can_admin: true,
      can_edit: true,
      can_review: true,
      can_export: true,
    },
  }),
}))

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const approved = 'Human approved text'
const draft = 'Fresh draft from regenerate.'
let posts: { url: string; method: string }[]
let showStale = false

beforeEach(() => {
  posts = []
  showStale = false
  vi.stubGlobal(
    'fetch',
    async (input: string | URL | Request, init: RequestInit = {}) => {
      const url = String(input)
      const method = (init.method || 'GET').toUpperCase()
      if (method === 'POST') {
        posts.push({ url, method })
        if (url.endsWith('/regenerate')) {
          return json({
            id: 11,
            text: approved,
            status: 'approved',
            draft_revision: {
              id: 4,
              revision_number: 1,
              text: draft,
              citations: '[{"chunk_id":41,"snippet":"synthetic evidence"}]',
              status: 'draft',
            },
          })
        }
        return json({
          id: 11,
          text: draft,
          status: 'approved',
          draft_revision: null,
        })
      }
      if (url.includes('/api/questionnaires/9')) {
        return json({
          id: 9,
          filename: 'questions.xlsx',
          questions: [
            {
              id: 3,
              text: 'Describe access reviews.',
              answer: {
                id: 11,
                text: approved,
                status: 'approved',
                citations: '[{"chunk_id":1,"snippet":"approved snippet"}]',
                support_stale: showStale,
                draft_revision: {
                  id: 4,
                  revision_number: 1,
                  text: draft,
                  citations: '[{"chunk_id":41,"snippet":"synthetic evidence"}]',
                  status: 'draft',
                },
              },
            },
          ],
        })
      }
      if (url.includes('/api/exports/records')) return json({ records: [] })
      if (url.includes('/api/workspaces/current')) {
        return json({
          id: 7,
          ai_completion_model: 'gpt-4o-mini',
          ai_temperature: 0.35,
        })
      }
      if (url.includes('/unread-count')) return json({ count: 0 })
      throw new Error(`Unexpected read: ${url}`)
    }
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('approved answer beside a draft revision', () => {
  it('shows the approved text and the draft, and posts regenerate and reapproval', async () => {
    render(createElement(ReviewPage))
    const approvedNode = await screen.findByText(approved)
    const draftNode = await screen.findByText(draft)
    expect(approvedNode.closest('[data-approved-answer]')).toBeTruthy()
    expect(draftNode.closest('[data-draft-revision="1"]')).toBeTruthy()
    expect(screen.queryByPlaceholderText('Edit draft answer…')).toBeNull()
    expect(screen.getByText(/Export uses this approved answer/)).toBeTruthy()
    expect(screen.queryByText('Stale source')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Regenerate' }))
    await waitFor(() =>
      expect(
        posts.some((post) => post.url === '/api/answers/11/regenerate')
      ).toBe(true)
    )

    fireEvent.click(screen.getByRole('button', { name: 'Approve draft' }))
    await waitFor(() =>
      expect(
        posts.some((post) => post.url === '/api/answers/11/revisions/4/approve')
      ).toBe(true)
    )
  })

  it('shows the stale marker when the questionnaire says the revision is stale', async () => {
    showStale = true
    render(createElement(ReviewPage))
    const marker = await screen.findByText('Stale source')
    expect(marker.getAttribute('data-support-stale')).toBe('true')
    expect(screen.getByText(approved)).toBeTruthy()
  })
})
