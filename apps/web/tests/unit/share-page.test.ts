// @vitest-environment happy-dom

import { createElement } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SharePage from '@/app/share/page'

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams('token=buyer-link'),
}))
vi.mock('next/navigation', () => ({
  useSearchParams: () => navigation.params,
}))

const publishedTitle = 'Published control title'
const publishedContent = 'Published control text'
const approvedText = 'Approved answer text'
const hiddenTitle = 'Hidden draft title'
const hiddenCitation = 'citation-should-stay-hidden'
const buyerEmail = 'buyer@example.com'

let accessBody: unknown
let articleReads: Record<string, { status: number; body: unknown }>
let answerReads: Record<string, { status: number; body: unknown }>
const calls: string[] = []

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  navigation.params = new URLSearchParams('token=buyer-link')
  accessBody = {
    valid: true,
    space: {
      id: 41,
      name: 'Synthetic room',
      buyer_email: buyerEmail,
      workspace_id: 7,
      access_token: null,
    },
    article_ids: [3],
    answer_ids: [5],
    document_ids: [9],
  }
  articleReads = {
    '3': {
      status: 200,
      body: {
        id: 3,
        title: publishedTitle,
        content: publishedContent,
        draft_title: hiddenTitle,
      },
    },
  }
  answerReads = {
    '5': {
      status: 200,
      body: {
        id: 5,
        text: approvedText,
        status: 'approved',
        citations: [hiddenCitation],
      },
    },
  }
  calls.length = 0
  vi.stubGlobal('fetch', (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    if (url.startsWith('/api/shareable-spaces/access?'))
      return Promise.resolve(json(accessBody))
    const article = url.match(
      /^\/api\/shareable-spaces\/access\/articles\/(\d+)\?/
    )
    if (article) {
      const found = articleReads[article[1]]
      if (!found) return Promise.reject(new Error(`unexpected ${url}`))
      return Promise.resolve(json(found.body, found.status))
    }
    const answer = url.match(
      /^\/api\/shareable-spaces\/access\/answers\/(\d+)\?/
    )
    if (answer) {
      const found = answerReads[answer[1]]
      if (!found) return Promise.reject(new Error(`unexpected ${url}`))
      return Promise.resolve(json(found.body, found.status))
    }
    return Promise.reject(new Error(`unexpected ${url}`))
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function open() {
  render(createElement(SharePage))
  return screen.findByRole('heading', { level: 1 })
}

it('shows the articles, answers, and documents from the access payload', async () => {
  const heading = await open()
  expect(heading.textContent).toBe('Synthetic room')
  expect(
    await screen.findByRole('heading', { name: publishedTitle })
  ).toBeTruthy()
  expect(screen.getByText(publishedContent)).toBeTruthy()
  expect(screen.getByText(approvedText)).toBeTruthy()
  const download = screen.getByRole('link', { name: 'Download document 9' })
  expect(download.getAttribute('href')).toBe(
    '/api/shareable-spaces/access/documents/9/content?token=buyer-link'
  )
  expect(download.getAttribute('referrerpolicy')).toBe('no-referrer')
  expect(screen.queryByText(hiddenTitle)).toBeNull()
  expect(screen.queryByText(hiddenCitation)).toBeNull()
  expect(screen.queryByText(buyerEmail)).toBeNull()
  expect(document.body.textContent).not.toContain('buyer-link')
  expect(calls.some((url) => url.startsWith('/api/trust-articles'))).toBe(false)
  expect(calls.some((url) => url.startsWith('/api/documents'))).toBe(false)
  expect(calls.some((url) => url.startsWith('/api/answers'))).toBe(false)
  expect(calls.filter((url) => url.includes('/articles/'))).toEqual([
    '/api/shareable-spaces/access/articles/3?token=buyer-link',
  ])
})

it('does not show an article that is absent from the access payload', async () => {
  accessBody = {
    valid: true,
    space: { id: 41, name: 'Synthetic room' },
    article_ids: [3],
    answer_ids: [],
    document_ids: [],
  }
  articleReads['8'] = {
    status: 200,
    body: { id: 8, title: hiddenTitle, content: 'draft body' },
  }
  await open()
  expect(
    await screen.findByRole('heading', { name: publishedTitle })
  ).toBeTruthy()
  expect(screen.queryByText(hiddenTitle)).toBeNull()
  expect(calls.some((url) => url.includes('/articles/8'))).toBe(false)
})

it('shows the access reason and no lists when the token is not valid', async () => {
  accessBody = { valid: false, reason: 'Space expired' }
  const heading = await open()
  expect(heading.textContent).toBe('This link is not available')
  expect(screen.getByText('Space expired')).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Articles' })).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Answers' })).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Documents' })).toBeNull()
  expect(calls).toEqual(['/api/shareable-spaces/access?token=buyer-link'])
})

it('does not call the API when the token is missing', async () => {
  navigation.params = new URLSearchParams()
  const heading = await open()
  expect(heading.textContent).toBe('This link is not available')
  expect(screen.getByText('This link is invalid or has expired.')).toBeTruthy()
  expect(calls).toEqual([])
})

it('shows an empty section when a list in the payload is empty', async () => {
  accessBody = {
    valid: true,
    space: { id: 41, name: 'Synthetic room' },
    article_ids: [],
    answer_ids: [],
    document_ids: [],
  }
  await open()
  expect(await screen.findByRole('heading', { name: 'Articles' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Answers' })).toBeTruthy()
  expect(screen.getByRole('heading', { name: 'Documents' })).toBeTruthy()
  expect(screen.getAllByText('None listed.')).toHaveLength(3)
})

it('omits an article the token read does not return', async () => {
  accessBody = {
    valid: true,
    space: { id: 41, name: 'Synthetic room' },
    article_ids: [3, 4],
    answer_ids: [],
    document_ids: [],
  }
  articleReads['4'] = { status: 404, body: { detail: 'Not found' } }
  await open()
  expect(
    await screen.findByRole('heading', { name: publishedTitle })
  ).toBeTruthy()
  expect(screen.queryByText('Not found')).toBeNull()
  expect(screen.getAllByRole('listitem')).toHaveLength(1)
})
