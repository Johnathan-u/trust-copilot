import { describe, expect, it } from 'vitest'
import { autoDismissMs } from '@/lib/toast'
import {
  DESTRUCTIVE_CONFIRM_ERROR_FALLBACK,
  DESTRUCTIVE_CONFIRM_ERROR_TITLE,
  destructiveConfirmErrorToast,
  nextDestructiveConfirmState,
} from '@/lib/destructive-confirm'

describe('destructive confirm failures', () => {
  it('formats an API detail and a TC-11-001 error with apiErrorAnnouncement or apiErrorMessage', () => {
    const detail = destructiveConfirmErrorToast({
      detail: 'Workspace denied',
    })
    expect(detail).toEqual({
      title: DESTRUCTIVE_CONFIRM_ERROR_TITLE,
      message: 'Workspace denied',
      severity: 'error',
      autoDismissMs: null,
    })
    expect(autoDismissMs(detail.severity)).toBeNull()

    const info = destructiveConfirmErrorToast({
      code: 'hidden_provider',
      message: 'The model could not answer',
      request_id: 'abcdef0123456789',
      retryable: false,
    })
    expect(info.message).toBe('The model could not answer (ref abcdef01)')
    expect(
      destructiveConfirmErrorToast({
        error: {
          code: 'denied',
          message: 'Not in this workspace',
          request_id: 'zzzzzzzz',
        },
      }).message
    ).toBe('Not in this workspace (ref zzzzzzzz)')
  })

  it('keeps a thrown string or Error, and closes without a stuck busy state', () => {
    expect(
      destructiveConfirmErrorToast(new Error('network down')).message
    ).toBe('network down')
    expect(destructiveConfirmErrorToast('  disk full  ').message).toBe(
      'disk full'
    )
    expect(destructiveConfirmErrorToast(null).message).toBe(
      DESTRUCTIVE_CONFIRM_ERROR_FALLBACK
    )

    expect(nextDestructiveConfirmState('fulfilled')).toEqual({
      open: false,
      busy: false,
      announceError: false,
      returnFocus: 'trigger',
    })
    expect(nextDestructiveConfirmState('rejected')).toEqual({
      open: false,
      busy: false,
      announceError: true,
      returnFocus: 'trigger',
    })
  })
})
