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
import JobsPage from '@/app/dashboard/jobs/page'

const auth = vi.hoisted(() => ({
  workspace: { id: 7 },
  loading: false,
  permissions: { can_review: true, can_admin: true },
}))
const navigation = vi.hoisted(() => ({ query: '', push: vi.fn() }))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
  useRouter: () => ({ push: navigation.push }),
}))
const row = {
  id: 41,
  kind: 'generate_answers',
  status: 'running',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:00:00',
  completed_at: null,
  charge_uncertain: true,
  progress: { generated: 2, total: 5 },
  object_ref: { type: 'questionnaire', id: 9 },
}
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}
let fetcher: (url: string, init: RequestInit) => Promise<Response>
let calls: Array<{ url: string; init: RequestInit }>
beforeEach(() => {
  auth.workspace = { id: 7 }
  auth.loading = false
  auth.permissions = { can_review: true, can_admin: true }
  navigation.query = ''
  navigation.push.mockReset()
  calls = []
  fetcher = async (url, init) =>
    init.method === 'POST'
      ? json({
          ...row,
          status: url.includes('/cancel?') ? 'cancelled' : 'queued',
        })
      : url.includes('/jobs/41?')
        ? json({ ...row, result: { generated: 3, total: 5 }, error: 'SECRET' })
        : json({ items: [row], next_before_id: null })
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(url), init })
    return fetcher(String(url), init)
  })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function open() {
  const view = render(createElement(JobsPage))
  await screen.findByRole('article', { name: 'Generate answers' })
  return view
}
it('reads once in StrictMode and displays safe progress and authorized links', async () => {
  render(createElement(StrictMode, null, createElement(JobsPage)))
  await screen.findByText('2 of 5 answers generated')
  expect(calls).toHaveLength(1)
  expect(calls[0].url).toBe('/api/jobs?workspace_id=7&limit=25')
  expect(
    screen
      .getByRole('link', { name: 'Open questionnaire' })
      .getAttribute('href')
  ).toBe('/dashboard/questionnaires/9')
  expect(screen.getByText(/may have been charged/)).toBeTruthy()
})
it('keeps cursor pagination in a workspace-bound URL, including a fresh mount', async () => {
  fetcher = async () => json({ items: [row], next_before_id: 41 })
  const view = await open()
  fireEvent.click(screen.getByRole('button', { name: 'Older jobs' }))
  expect(navigation.push).toHaveBeenCalledWith(
    '/dashboard/jobs?workspace_id=7&before_id=41'
  )
  view.unmount()
  navigation.query = 'workspace_id=7&before_id=41'
  fetcher = async () =>
    json({ items: [{ ...row, id: 40 }], next_before_id: null })
  await open()
  expect(calls.at(-1)?.url).toContain('&before_id=41')
  expect(screen.getByRole('button', { name: 'Newest jobs' })).toBeTruthy()
})
it.each([false, true])(
  'uses current capability flags, can_review=%s',
  async (canReview) => {
    auth.permissions = { can_review: canReview, can_admin: false }
    render(createElement(JobsPage))
    if (canReview) await screen.findByText('2 of 5 answers generated')
    else {
      await screen.findByText('Job access is restricted')
      expect(calls).toHaveLength(0)
    }
    expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
  }
)
it('discards a late list response and old cursor when the workspace changes', async () => {
  const old = deferred<Response>()
  navigation.query = 'workspace_id=7&before_id=42'
  fetcher = async (url) =>
    url.includes('workspace_id=7')
      ? old.promise
      : json({
          items: [{ ...row, kind: 'export', id: 81 }],
          next_before_id: null,
        })
  const view = render(createElement(JobsPage))
  await waitFor(() => expect(calls).toHaveLength(1))
  auth.workspace = { id: 8 }
  view.rerender(createElement(JobsPage))
  await screen.findByRole('article', { name: 'Export questionnaire' })
  await act(async () =>
    old.resolve(json({ items: [row], next_before_id: null }))
  )
  expect(screen.queryByRole('article', { name: 'Generate answers' })).toBeNull()
  expect(calls.at(-1)?.url).toBe('/api/jobs?workspace_id=8&limit=25')
  expect(calls[0].init.signal?.aborted).toBe(true)
})
it('consumes its aborted promise on unmount without an unhandled rejection', async () => {
  fetcher = async (_url, init) =>
    new Promise((_resolve, reject) =>
      init.signal?.addEventListener('abort', () =>
        reject(new DOMException('aborted', 'AbortError'))
      )
    )
  const view = render(createElement(JobsPage))
  await waitFor(() => expect(calls).toHaveLength(1))
  view.unmount()
  await act(async () => Promise.resolve())
  expect(calls[0].init.signal?.aborted).toBe(true)
})
it('shows malformed success as an error and recovers on explicit reload', async () => {
  fetcher = async () => json({ unexpected: [] })
  render(createElement(JobsPage))
  await screen.findByRole('alert')
  expect(screen.queryByText('No jobs yet')).toBeNull()
  fetcher = async () => json({ items: [], next_before_id: null })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await screen.findByText('No jobs yet')
})
it('filters legacy detail and does not derive an object link from its raw payload', async () => {
  await open()
  fireEvent.click(screen.getByRole('button', { name: 'View details' }))
  const dialog = await screen.findByRole('dialog', { name: 'Job details' })
  await within(dialog).findByText('3 of 5 answers generated')
  expect(dialog.textContent).not.toContain('SECRET')
  expect(within(dialog).queryByRole('link')).toBeNull()
})
it('waits for the exact cancellation acknowledgment and prevents duplicate submissions', async () => {
  const pending = deferred<Response>()
  await open()
  fetcher = async (_url, init) =>
    init.method === 'POST'
      ? pending.promise
      : json({ items: [{ ...row, status: 'cancelled' }], next_before_id: null })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  const dialog = screen.getByRole('alertdialog', { name: 'Cancel this job?' })
  const confirm = within(dialog).getByRole('button', { name: 'Cancel job' })
  fireEvent.click(confirm)
  fireEvent.click(confirm)
  expect(calls.filter((c) => c.init.method === 'POST')).toHaveLength(1)
  expect(screen.queryByText('Job cancelled.')).toBeNull()
  expect(screen.getByText('Running')).toBeTruthy()
  await act(async () => pending.resolve(json({ ...row, status: 'cancelled' })))
  await screen.findByText('Job cancelled.')
  await screen.findByText('Cancelled')
})
it.each([409, 403, 404, 500, 200])(
  'never announces success after denied, failed or malformed acknowledgment %s',
  async (status) => {
    await open()
    fetcher = async (_url, init) =>
      init.method !== 'POST' && status === 403
        ? json({ items: [row], next_before_id: null })
        : json(
            status === 200
              ? { ...row, id: 42, status: 'cancelled' }
              : { detail: 'SECRET' },
            status
          )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel job',
      })
    )
    await screen.findByRole('alert')
    expect(screen.queryByText('Job cancelled.')).toBeNull()
    await screen.findByText('Running')
    if (status === 403) {
      await waitFor(() =>
        expect(
          calls.filter((c) => c.url === '/api/jobs?workspace_id=7&limit=25')
        ).toHaveLength(2)
      )
      expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
    }
    expect(document.body.textContent).not.toContain('SECRET')
  }
)
it('clears detail, mutation and notices when access or workspace changes', async () => {
  const pending = deferred<Response>()
  const view = await open()
  fetcher = async (_url, init) =>
    init.method === 'POST'
      ? pending.promise
      : json({
          items: [{ ...row, kind: 'export', id: 81 }],
          next_before_id: null,
        })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Cancel job',
    })
  )
  auth.workspace = { id: 8 }
  view.rerender(createElement(JobsPage))
  await screen.findByRole('article', { name: 'Export questionnaire' })
  await act(async () => pending.resolve(json({ ...row, status: 'cancelled' })))
  expect(screen.queryByText('Job cancelled.')).toBeNull()
  expect(screen.queryByRole('alertdialog')).toBeNull()
  auth.permissions.can_review = false
  view.rerender(createElement(JobsPage))
  expect(screen.queryByRole('article')).toBeNull()
})
it('discards detail that resolves after moving to another workspace', async () => {
  const pending = deferred<Response>()
  const view = await open()
  fetcher = async (url) =>
    url.includes('/jobs/41?')
      ? pending.promise
      : json({
          items: [{ ...row, kind: 'export', id: 81 }],
          next_before_id: null,
        })
  fireEvent.click(screen.getByRole('button', { name: 'View details' }))
  await waitFor(() =>
    expect(calls.some((c) => c.url.includes('/jobs/41?'))).toBe(true)
  )
  auth.workspace = { id: 8 }
  view.rerender(createElement(JobsPage))
  await screen.findByRole('article', { name: 'Export questionnaire' })
  await act(async () =>
    pending.resolve(json({ ...row, result: { generated: 5, total: 5 } }))
  )
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.queryByText('5 of 5 answers generated')).toBeNull()
})
it('revoking admin capability dismisses confirmation without sending a mutation', async () => {
  const view = await open()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  auth.permissions.can_admin = false
  view.rerender(createElement(JobsPage))
  await screen.findByRole('article', { name: 'Generate answers' })
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
  expect(calls.filter((c) => c.init.method === 'POST')).toHaveLength(0)
})
it('retains an acknowledged retry when refreshing history fails, with an explicit partial state', async () => {
  fetcher = async () =>
    json({
      items: [{ ...row, status: 'failed', retries_exhausted: true }],
      next_before_id: null,
    })
  await open()
  fetcher = async (_url, init) =>
    init.method === 'POST'
      ? json({ ...row, status: 'queued', attempt: 0 })
      : json({ detail: 'SECRET' }, 500)
  fireEvent.click(screen.getByRole('button', { name: 'Retry job' }))
  const dialog = screen.getByRole('alertdialog', { name: 'Retry this job?' })
  expect(dialog.textContent).toContain('may have been charged')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Retry job' }))
  await screen.findByText('Another attempt is queued.')
  await screen.findByText(/last confirmed results/)
  expect(screen.getByText('Queued')).toBeTruthy()
  expect(
    screen.getByRole('button', { name: 'Cancel job' }).hasAttribute('disabled')
  ).toBe(true)
})
it('clears a previous acknowledgment before starting another action', async () => {
  await open()
  fetcher = async (_url, init) =>
    init.method === 'POST'
      ? json({ ...row, status: 'cancelled' })
      : json({ items: [{ ...row, status: 'cancelled' }], next_before_id: null })
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Cancel job',
    })
  )
  await screen.findByText('Job cancelled.')
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Retry job' }).hasAttribute('disabled')
    ).toBe(false)
  )
  fireEvent.click(screen.getByRole('button', { name: 'Retry job' }))
  expect(screen.queryByText('Job cancelled.')).toBeNull()
})
it('rejects invalid saved cursor without making a business request', async () => {
  navigation.query = 'workspace_id=7&before_id=private-value'
  render(createElement(JobsPage))
  await screen.findByText('This history page is unavailable')
  expect(calls).toHaveLength(0)
  expect(document.body.textContent).not.toContain('private-value')
})
it('shows unavailable detail separately from the successful history', async () => {
  await open()
  fetcher = async () => json({ detail: 'SECRET' }, 404)
  fireEvent.click(screen.getByRole('button', { name: 'View details' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('We could not find that')
  expect(document.body.textContent).not.toContain('SECRET')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  expect(screen.getByRole('article', { name: 'Generate answers' })).toBeTruthy()
})
it.each([401, 403, 404])(
  'clears previously loaded history when its next read loses access (%s)',
  async (status) => {
    await open()
    fetcher = async () => json({ detail: 'PRIVATE_DENIAL' }, status)
    fireEvent.click(screen.getByRole('button', { name: 'Reload jobs' }))
    await screen.findByRole('alert')
    expect(screen.queryByRole('article')).toBeNull()
    expect(
      screen.queryByRole('link', { name: 'Open questionnaire' })
    ).toBeNull()
  }
)
it.each([401, 403])(
  'detail read denial %s invalidates history and rejects a late history response',
  async (status) => {
    await open()
    const pending = deferred<Response>()
    fetcher = async (url) =>
      url.includes('/jobs/41?')
        ? json({ detail: 'PRIVATE_DENIAL' }, status)
        : pending.promise
    fireEvent.click(screen.getByRole('button', { name: 'Reload jobs' }))
    await waitFor(() => expect(calls).toHaveLength(2))
    fireEvent.click(screen.getByRole('button', { name: 'View details' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(screen.queryByRole('article')).toBeNull()
      expect(
        screen.queryByRole('link', { name: 'Open questionnaire' })
      ).toBeNull()
    })
    expect(calls[1].init.signal?.aborted).toBe(true)
    await act(async () =>
      pending.resolve(json({ items: [row], next_before_id: null }))
    )
    expect(screen.queryByRole('article')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
    expect(document.body.textContent).not.toContain('PRIVATE_DENIAL')
  }
)
it.each([401, 403, 404])(
  'history read denial %s closes pending detail and rejects its late response',
  async (status) => {
    await open()
    const list = deferred<Response>()
    const detail = deferred<Response>()
    fetcher = async (url) =>
      url.includes('/jobs/41?') ? detail.promise : list.promise
    fireEvent.click(screen.getByRole('button', { name: 'Reload jobs' }))
    await waitFor(() => expect(calls).toHaveLength(2))
    fireEvent.click(screen.getByRole('button', { name: 'View details' }))
    await waitFor(() => expect(calls).toHaveLength(3))
    await act(async () =>
      list.resolve(json({ detail: 'PRIVATE_DENIAL' }, status))
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls[2].init.signal?.aborted).toBe(true)
    await act(async () =>
      detail.resolve(json({ ...row, result: { generated: 5, total: 5 } }))
    )
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('article')).toBeNull()
    expect(screen.queryByText('5 of 5 answers generated')).toBeNull()
  }
)
it('a history denial also removes already loaded detail', async () => {
  await open()
  const list = deferred<Response>()
  fetcher = async (url) =>
    url.includes('/jobs/41?')
      ? json({ ...row, result: { generated: 5, total: 5 } })
      : list.promise
  fireEvent.click(screen.getByRole('button', { name: 'Reload jobs' }))
  await waitFor(() => expect(calls).toHaveLength(2))
  fireEvent.click(screen.getByRole('button', { name: 'View details' }))
  await screen.findByText('5 of 5 answers generated')
  await act(async () => list.resolve(json({ detail: 'PRIVATE_DENIAL' }, 403)))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.queryByText('5 of 5 answers generated')).toBeNull()
})
it('mutation401 clears session-owned history without declaring success', async () => {
  await open()
  fetcher = async () => json({ detail: 'PRIVATE_DENIAL' }, 401)
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Cancel job',
    })
  )
  await screen.findByRole('alert')
  expect(screen.queryByRole('article')).toBeNull()
  expect(screen.queryByRole('link', { name: 'Open questionnaire' })).toBeNull()
  expect(screen.queryByText('Job cancelled.')).toBeNull()
})
it('mutation403 requires a new history acknowledgment before restoring read-only rows', async () => {
  await open()
  const list = deferred<Response>()
  fetcher = async (_url, init) =>
    init.method === 'POST'
      ? json({ detail: 'PRIVATE_DENIAL' }, 403)
      : list.promise
  fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
  fireEvent.click(
    within(screen.getByRole('alertdialog')).getByRole('button', {
      name: 'Cancel job',
    })
  )
  await waitFor(() =>
    expect(calls.filter((c) => c.init.method !== 'POST')).toHaveLength(2)
  )
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(screen.queryByRole('article', { hidden: true })).toBeNull()
  expect(screen.queryByRole('link', { name: 'Open questionnaire' })).toBeNull()
  await act(async () =>
    list.resolve(json({ items: [row], next_before_id: null }))
  )
  await screen.findByRole('article', { name: 'Generate answers' })
  expect(screen.getByRole('link', { name: 'Open questionnaire' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
  expect(screen.queryByText('Job cancelled.')).toBeNull()
})
it.each([403, 404, 500])(
  'mutation403 followed by history%s never restores stale rows',
  async (status) => {
    await open()
    fetcher = async (_url, init) =>
      json({ detail: 'PRIVATE_DENIAL' }, init.method === 'POST' ? 403 : status)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
    fireEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', {
        name: 'Cancel job',
      })
    )
    await waitFor(() =>
      expect(calls.filter((c) => c.init.method !== 'POST')).toHaveLength(2)
    )
    await waitFor(() => expect(screen.queryByRole('article')).toBeNull())
    expect(
      screen.queryByRole('link', { name: 'Open questionnaire' })
    ).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cancel job' })).toBeNull()
  }
)
