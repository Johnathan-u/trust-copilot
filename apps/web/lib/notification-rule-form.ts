export const USER_RECIPIENT_LABEL = 'Workspace member'
export const USER_RECIPIENT_HELP =
  "Choose an active workspace member. The rule stores that member's user id."
export const ROLE_RECIPIENT_LABEL = 'Role name'
export const RECIPIENT_VALUE_MAX_LENGTH = 255
export const POLICY_FORM_UNREADABLE_ERROR =
  'The rule could not be saved. Check the event and recipient, then try again.'

export type WorkspaceMemberOption = {
  user_id: number
  display_name: string
  email: string
  suspended: boolean
}

/** A create-rule error is always a string. A non-string `detail` is not rendered. */
export function policyCreateErrorMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail.trim() ? detail : 'Failed'
  if (detail == null) return 'Failed'
  return POLICY_FORM_UNREADABLE_ERROR
}

export function readWorkspaceMembers(value: unknown): WorkspaceMemberOption[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid members')
  }
  const members = (value as { members?: unknown }).members
  if (!Array.isArray(members)) throw new Error('Invalid members')
  return members.map((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw new Error('Invalid member')
    }
    const row = item as Record<string, unknown>
    const userId = row.user_id
    if (
      typeof userId !== 'number' ||
      !Number.isSafeInteger(userId) ||
      userId <= 0 ||
      typeof row.email !== 'string' ||
      typeof row.display_name !== 'string' ||
      typeof row.suspended !== 'boolean'
    ) {
      throw new Error('Invalid member')
    }
    return {
      user_id: userId,
      display_name: row.display_name,
      email: row.email,
      suspended: row.suspended,
    }
  })
}

export function activeWorkspaceMembers(
  members: WorkspaceMemberOption[]
): WorkspaceMemberOption[] {
  return members.filter((member) => !member.suspended)
}
