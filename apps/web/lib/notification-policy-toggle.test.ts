import { describe, expect, it, vi } from 'vitest'

import { toggleNotificationPolicy } from '@/lib/notification-policy-toggle'

function response(status: number, body: string, statusText: string): Response {
  return new Response(body, {
    status,
    statusText,
    headers: { 'content-type': 'application/json' },
  })
}

describe('toggleNotificationPolicy', () => {
  it('shows the API error, reloads, and does not reject', async () => {
    const reload = vi.fn()
    const setError = vi.fn()
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      response(409, JSON.stringify({ detail: 'Policy not found' }), 'Conflict')
    )
    const unhandled: unknown[] = []
    const onUnhandled = (reason: unknown) => {
      unhandled.push(reason)
    }
    process.on('unhandledRejection', onUnhandled)

    try {
      const pending = toggleNotificationPolicy(
        { id: 4, enabled: true },
        { reload, setError },
        fetchImpl
      )
      await expect(pending).resolves.toBeUndefined()
      await new Promise((resolve) => setImmediate(resolve))
    } finally {
      process.off('unhandledRejection', onUnhandled)
    }

    expect(unhandled).toEqual([])
    expect(setError).toHaveBeenCalledTimes(1)
    expect(setError).toHaveBeenCalledWith('Policy not found')
    expect(reload).toHaveBeenCalledOnce()
    expect(fetchImpl).toHaveBeenCalledWith('/api/notifications/policies/4', {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: false }),
    })
  })

  it('clears an earlier error after a successful toggle', async () => {
    const reload = vi.fn()
    let error: string | null = 'Policy not found'
    const fetchImpl = vi.fn<typeof fetch>(async () => response(200, '', 'OK'))

    await toggleNotificationPolicy(
      { id: 4, enabled: false },
      {
        reload,
        setError: (message) => {
          error = message
        },
      },
      fetchImpl
    )

    expect(error).toBeNull()
    expect(reload).toHaveBeenCalledOnce()
  })
})
