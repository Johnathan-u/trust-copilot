import { describe, expect, it } from 'vitest'

import {
  POLICY_FORM_UNREADABLE_ERROR,
  RECIPIENT_VALUE_MAX_LENGTH,
  activeWorkspaceMembers,
  policyCreateErrorMessage,
  readWorkspaceMembers,
} from '@/lib/notification-rule-form'

describe('policyCreateErrorMessage', () => {
  it('keeps a string detail and replaces a non-string with a fixed message', () => {
    expect(policyCreateErrorMessage('Recipient not found')).toBe(
      'Recipient not found'
    )
    expect(policyCreateErrorMessage('')).toBe('Failed')
    expect(policyCreateErrorMessage(null)).toBe('Failed')
    expect(policyCreateErrorMessage(undefined)).toBe('Failed')

    const validationList = [
      {
        loc: ['body', 'recipient_value'],
        msg: 'String should have at most 255 characters',
        type: 'string_too_long',
      },
    ]
    const message = policyCreateErrorMessage(validationList)
    expect(message).toBe(POLICY_FORM_UNREADABLE_ERROR)
    expect(typeof message).toBe('string')
    expect(message).not.toContain('string_too_long')
    expect(policyCreateErrorMessage({ msg: 'not a string' })).toBe(
      POLICY_FORM_UNREADABLE_ERROR
    )
  })
})

describe('readWorkspaceMembers', () => {
  it('uses the member user id and leaves suspended members out of the active list', () => {
    const members = readWorkspaceMembers({
      members: [
        {
          id: 90,
          user_id: 17,
          email: 'ada.member@example.com',
          display_name: 'Ada Member',
          role: 'editor',
          suspended: false,
        },
        {
          id: 91,
          user_id: 18,
          email: 'paused.member@example.com',
          display_name: 'Paused Member',
          role: 'editor',
          suspended: true,
        },
      ],
    })
    expect(members.map((member) => member.user_id)).toEqual([17, 18])
    expect(
      activeWorkspaceMembers(members).map((member) => member.user_id)
    ).toEqual([17])
    expect(RECIPIENT_VALUE_MAX_LENGTH).toBe(255)
  })
})
