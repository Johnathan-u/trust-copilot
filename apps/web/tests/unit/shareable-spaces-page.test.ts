// @vitest-environment happy-dom

import { createElement, Fragment } from 'react'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ShareableSpacesPage from '@/app/dashboard/shareable-spaces/page'
import { ToastLiveRegions } from '@/components/ui/Toast'
import { buyerAccessLink } from '@/lib/shareable-space-link'

const context = vi.hoisted(() => ({
  user: { id: 42 },
  workspace: { id: 7 },
  loading: false,
  permissions: { can_admin: true, can_edit: true, can_review: true },
}))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => context }))

const live = {
  id: 41,
  workspace_id: 7,
  name: 'Synthetic room',
  buyer_company: 'Synthetic Buyer',
  buyer_email: 'buyer@example.com',
  opportunity_id: 'opp-synthetic',
  access_token: null,
  has_access_token: true,
  is_active: true,
  expires_at: '2099-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
}
const openEnded = {
  ...live,
  id: 42,
  name: 'Open ended',
  expires_at: null,
}
const inactive = {
  ...live,
  id: 43,
  name: 'Closed room',
  is_active: false,
  has_access_token: true,
}
const expired = {
  ...live,
  id: 44,
  name: 'Old room',
  is_active: true,
  expires_at: '2000-01-01T00:00:00Z',
}

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status })

let rows: unknown[]
let writes: Array<{ path: string; init: RequestInit }>
let rotateStatus: number
let rotateBody: unknown
let stored: string[]

beforeEach(() => {
  context.permissions = { can_admin: true, can_edit: true, can_review: true }
  rows = [live, openEnded, inactive, expired]
  writes = []
  rotateStatus = 200
  rotateBody = {
    ...live,
    access_token: 'rotated-token',
    has_access_token: true,
  }
  stored = []
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
    stored.push(`${key}=${value}`)
  })
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    if (init.method === 'POST') {
      writes.push({ path, init })
      return Promise.resolve(json(rotateBody, rotateStatus))
    }
    if (path === '/api/shareable-spaces')
      return Promise.resolve(json({ spaces: rows }))
    return Promise.reject(new Error(`unexpected ${path}`))
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function open() {
  render(
    createElement(
      Fragment,
      null,
      createElement(ToastLiveRegions),
      createElement(ShareableSpacesPage)
    )
  )
  await screen.findByRole('heading', { name: 'Shareable spaces' })
  await screen.findByText('Synthetic room')
}

it('shows Rotate link only to admins and only on live spaces', async () => {
  await open()
  expect(
    screen.getByRole('button', { name: 'Rotate link for Synthetic room' })
  ).toBeTruthy()
  expect(
    screen.getByRole('button', { name: 'Rotate link for Open ended' })
  ).toBeTruthy()
  expect(
    screen.queryByRole('button', { name: 'Rotate link for Closed room' })
  ).toBeNull()
  expect(
    screen.queryByRole('button', { name: 'Rotate link for Old room' })
  ).toBeNull()
  expect(screen.getAllByText('Live')).toHaveLength(2)
  expect(screen.getByText('Inactive')).toBeTruthy()
  expect(screen.getByText('Expired')).toBeTruthy()
  expect(document.body.textContent).not.toContain('rotated-token')
})

it('hides Rotate link from a non-admin', async () => {
  context.permissions = { can_admin: false, can_edit: true, can_review: true }
  await open()
  expect(screen.queryByRole('button', { name: /Rotate link/ })).toBeNull()
  expect(screen.getByText('Synthetic room')).toBeTruthy()
})

it('confirms that the old link stops immediately, then shows the new link once', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  await open()
  fireEvent.click(
    screen.getByRole('button', { name: 'Rotate link for Synthetic room' })
  )
  const confirm = await screen.findByRole('alertdialog', {
    name: 'Rotate link',
  })
  expect(confirm.textContent).toContain(
    'The old link will stop working immediately.'
  )
  expect(writes).toHaveLength(0)
  fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(writes).toHaveLength(0)

  fireEvent.click(
    screen.getByRole('button', { name: 'Rotate link for Synthetic room' })
  )
  const again = await screen.findByRole('alertdialog', { name: 'Rotate link' })
  fireEvent.click(within(again).getByRole('button', { name: 'Rotate link' }))
  const revealed = await screen.findByRole('dialog', { name: 'New buyer link' })
  const link = buyerAccessLink(window.location.origin, 'rotated-token')
  expect(within(revealed).getByText(link)).toBeTruthy()
  expect(revealed.textContent).toContain('shown once')
  expect(writes).toEqual([
    {
      path: '/api/shareable-spaces/41/rotate',
      init: expect.objectContaining({
        method: 'POST',
        credentials: 'include',
      }),
    },
  ])
  expect(writes[0].init.body).toBeUndefined()
  const table = screen.getByRole('table', { hidden: true })
  expect(table.textContent).not.toContain('rotated-token')
  fireEvent.click(within(revealed).getByRole('button', { name: 'Copy link' }))
  expect(writeText).toHaveBeenCalledWith(link)
  fireEvent.click(within(revealed).getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog', { name: 'New buyer link' })).toBeNull()
  expect(document.body.textContent).not.toContain('rotated-token')
  expect(stored.join('\n')).not.toContain('rotated-token')
  for (let index = 0; index < window.sessionStorage.length; index += 1) {
    const key = window.sessionStorage.key(index) ?? ''
    expect(`${key}=${window.sessionStorage.getItem(key)}`).not.toContain(
      'rotated-token'
    )
  }
})

it('does not reveal a link when rotation is refused', async () => {
  rotateStatus = 409
  rotateBody = {
    detail: 'This space is inactive and cannot be rotated.',
    access_token: 'leaked-token',
  }
  await open()
  fireEvent.click(
    screen.getByRole('button', { name: 'Rotate link for Synthetic room' })
  )
  const confirm = await screen.findByRole('alertdialog', {
    name: 'Rotate link',
  })
  fireEvent.click(within(confirm).getByRole('button', { name: 'Rotate link' }))
  await screen.findByText(
    'This space is inactive or expired and was not changed.'
  )
  expect(screen.queryByRole('dialog', { name: 'New buyer link' })).toBeNull()
  expect(document.body.textContent).not.toContain('leaked-token')
})
