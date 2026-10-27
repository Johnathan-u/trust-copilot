import { describe, expect, it, vi } from 'vitest'

import {
  DESTRUCTIVE_CONFIRM_ERROR_TITLE,
  destructiveConfirmErrorToast,
  nextDestructiveConfirmState,
} from '@/lib/destructive-confirm'
import { deleteNotificationPolicy } from '@/lib/notification-policy-delete'

function response(status: number, body: string, statusText: string): Response {
  return new Response(body, {
    status,
    statusText,
    headers: { 'content-type': 'application/json' },
  })
}

describe('deleteNotificationPolicy', () => {
  it('rejects a failed delete with the API message and fires the sticky error toast', async () => {
    const reload = vi.fn()
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      response(409, JSON.stringify({ detail: 'Policy not found' }), 'Conflict')
    )

    let caught: unknown
    await deleteNotificationPolicy(7, reload, fetchImpl).catch((reason) => {
      caught = reason
    })

    expect(caught).toBeInstanceOf(Error)
    expect((caught as Error).message).toBe('Policy not found')
    expect(reload).not.toHaveBeenCalled()
    expect(destructiveConfirmErrorToast(caught)).toEqual({
      title: DESTRUCTIVE_CONFIRM_ERROR_TITLE,
      message: 'Policy not found',
      severity: 'error',
      autoDismissMs: null,
    })
    expect(nextDestructiveConfirmState('rejected')).toEqual({
      open: false,
      busy: false,
      announceError: true,
      returnFocus: 'trigger',
    })
  })

  it('reloads after a successful delete', async () => {
    const reload = vi.fn()
    const fetchImpl = vi.fn<typeof fetch>(async () => response(200, '', 'OK'))

    await deleteNotificationPolicy(7, reload, fetchImpl)

    expect(fetchImpl).toHaveBeenCalledWith('/api/notifications/policies/7', {
      method: 'DELETE',
      credentials: 'include',
    })
    expect(reload).toHaveBeenCalledOnce()
  })

  it('falls back to the status text when the error body is not JSON', async () => {
    const reload = vi.fn()
    const fetchImpl = vi.fn<typeof fetch>(
      async () =>
        new Response('<html>down</html>', {
          status: 502,
          statusText: 'Bad Gateway',
        })
    )

    await expect(
      deleteNotificationPolicy(7, reload, fetchImpl)
    ).rejects.toThrow('Bad Gateway')
    expect(reload).not.toHaveBeenCalled()
  })
})
