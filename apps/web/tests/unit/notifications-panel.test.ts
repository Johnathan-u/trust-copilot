// @vitest-environment happy-dom

import { createElement, useState } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPanel } from '@/components/layout/NotificationsPanel'

let anchorRef: { current: HTMLDivElement | null }

function Harness() {
  const [open, setOpen] = useState(true)
  const [count, setCount] = useState(25)
  return createElement(
    'div',
    { ref: anchorRef },
    createElement('output', { 'aria-label': 'Unread badge' }, count),
    createElement('button', { onClick: () => setOpen(true) }, 'Open'),
    createElement(NotificationsPanel, {
      open,
      onClose: () => setOpen(false),
      onUnreadCountChange: setCount,
      anchorRef,
      panelId: 'notifications',
    })
  )
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let count: number
let mutate: () => Promise<Response>
let unread: () => Promise<Response>

beforeEach(() => {
  anchorRef = { current: null }
  count = 25
  mutate = async () => json({ ok: true })
  unread = async () => json({ count })
  vi.stubGlobal(
    'fetch',
    (input: string | URL | Request, init: RequestInit = {}) => {
      const url = String(input)
      if (init.method === 'POST') return mutate()
      if (url.endsWith('/unread-count')) return unread()
      if (url === '/api/in-app-notifications?limit=20') {
        return Promise.resolve(
          json({
            total: 25,
            notifications: Array.from({ length: 20 }, (_, i) => ({
              id: i + 1,
              title: `Notification ${i + 1}`,
              body: 'Synthetic notification.',
              category: 'info',
              link: null,
              is_read: false,
              admin_only: false,
              created_at: null,
            })),
          })
        )
      }
      throw new Error(`Unexpected request: ${url}`)
    }
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

async function openPanel() {
  render(createElement(Harness))
  await screen.findByText('Notification 20')
}

describe('notification read acknowledgements and authoritative count', () => {
  it('keeps the total unread count when the list has only 20 of 25 items', async () => {
    await openPanel()
    expect(screen.getByLabelText('Unread badge').textContent).toBe('25')
    expect(await screen.findByText('25 unread')).toBeTruthy()
  })

  it.each(['one', 'all'])(
    'preserves unread rows and count after a rejected mark-%s request',
    async (mode) => {
      mutate = async () => json({ detail: 'Forbidden' }, 403)
      await openPanel()
      fireEvent.click(
        mode === 'one'
          ? screen.getByText('Notification 1')
          : screen.getByRole('button', { name: 'Mark all read' })
      )
      expect(await screen.findByRole('alert')).toBeTruthy()
      expect(screen.getAllByTitle('Unread')).toHaveLength(20)
      expect(screen.getByLabelText('Unread badge').textContent).toBe('25')
    }
  )

  it('preserves unread state and presents a network failure without an unhandled rejection', async () => {
    mutate = async () => {
      throw new TypeError('Failed to fetch')
    }
    await openPanel()
    fireEvent.click(screen.getByText('Notification 1'))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getAllByTitle('Unread')).toHaveLength(20)
    expect(screen.getByLabelText('Unread badge').textContent).toBe('25')
  })

  it('refreshes the authoritative total after marking one row read', async () => {
    await openPanel()
    count = 24
    fireEvent.click(screen.getByText('Notification 1'))
    expect(await screen.findByText('24 unread')).toBeTruthy()
    expect(screen.getAllByTitle('Unread')).toHaveLength(19)
    expect(screen.getByLabelText('Unread badge').textContent).toBe('24')
  })

  it('uses the returned total after mark-all instead of inventing zero', async () => {
    await openPanel()
    count = 3 // New notifications arrived while the mutation was in flight.
    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }))
    expect(await screen.findByText('3 unread')).toBeTruthy()
    expect(screen.queryAllByTitle('Unread')).toHaveLength(0)
    expect(screen.getByLabelText('Unread badge').textContent).toBe('3')
  })

  it('refreshes the authoritative total when the list is reopened', async () => {
    await openPanel()
    fireEvent.click(screen.getByRole('button', { name: 'Close notifications' }))
    count = 42
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(await screen.findByText('42 unread')).toBeTruthy()
    expect(screen.getByLabelText('Unread badge').textContent).toBe('42')
  })

  it('does not replace the last confirmed count when the count refresh fails', async () => {
    await openPanel()
    unread = async () => json({ detail: 'Unavailable' }, 503)
    await act(async () => {
      fireEvent.click(screen.getByText('Notification 1'))
    })
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getAllByTitle('Unread')).toHaveLength(19)
    expect(screen.getByLabelText('Unread badge').textContent).toBe('25')
  })
})
