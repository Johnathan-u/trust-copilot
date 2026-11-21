import { mutationFailureNotice, presentHttpFailure } from '@/lib/api-error'

/** Shown when a 409 body has no detail string. Matches the API sentence. */
export const CARD_STALE_MESSAGE =
  'This card changed since it was loaded. Reload it and try again.'

export interface DashboardCardWriteSource {
  id?: number
  updated_at?: string | null
  is_builtin?: boolean
}

export interface CardSaveFields {
  title: string
  description: string
  icon: string
  targetRoute: string
  visibility: string
  size: string
  enabled: boolean
}

export interface CardSaveRequest {
  url: string
  method: 'POST' | 'PATCH'
  headers: Record<string, string>
  body: Record<string, unknown>
}

export interface CardCreateAttempt {
  fingerprint: string
  key: string
}

function cardBody(fields: CardSaveFields): Record<string, unknown> {
  return {
    title: fields.title.trim(),
    description: fields.description.trim() || null,
    icon: fields.icon,
    target_route: fields.targetRoute,
    visibility_scope: fields.visibility,
    size: fields.size,
    is_enabled: fields.enabled,
  }
}

/** Stable identity of one create body. A retry of the same fields keeps one key. */
export function cardCreateFingerprint(fields: CardSaveFields): string {
  return JSON.stringify(cardBody(fields))
}

/**
 * Reuse the key when the create body is unchanged. A new body gets a new key
 * so the API does not treat it as a different payload for the old key.
 */
export function nextCardCreateKey(
  previous: CardCreateAttempt | null,
  fingerprint: string,
  mint: () => string
): CardCreateAttempt {
  if (previous && previous.fingerprint === fingerprint) return previous
  return { fingerprint, key: mint() }
}

/**
 * Edit sends the updated_at the editor loaded. Create sends Idempotency-Key.
 * A built-in card is not a row: it has no id and no revision, so it is not patched.
 */
export function cardSaveRequest(input: {
  card: DashboardCardWriteSource | null
  fields: CardSaveFields
  createKey?: string
}): CardSaveRequest {
  const body = cardBody(input.fields)
  const editing = input.card?.id != null && input.card.is_builtin !== true
  if (editing) {
    body.updated_at = input.card?.updated_at ?? null
    return {
      url: `/api/dashboard/cards/${input.card?.id}`,
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body,
    }
  }
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (input.createKey) headers['Idempotency-Key'] = input.createKey
  return {
    url: '/api/dashboard/cards',
    method: 'POST',
    headers,
    body,
  }
}

export type CardSaveResult =
  { saved: true } | { saved: false; conflict: boolean; message: string }

/** 409 is not a save. The stored card is unchanged and the notice says so. */
export function cardSaveResult(status: number, data: unknown): CardSaveResult {
  if (status >= 200 && status < 300) return { saved: true }
  if (status === 409) {
    const detail =
      data &&
      typeof data === 'object' &&
      'detail' in data &&
      typeof (data as { detail?: unknown }).detail === 'string'
        ? (data as { detail: string }).detail
        : ''
    return {
      saved: false,
      conflict: true,
      message: detail.trim() || CARD_STALE_MESSAGE,
    }
  }
  const mapped = mutationFailureNotice(
    status,
    data,
    'The change was not saved. Try again.'
  )
  if (mapped.title === 'Could not complete that') {
    const failure = presentHttpFailure({ status })
    return {
      saved: false,
      conflict: false,
      message: `${failure.title}. ${failure.description}`,
    }
  }
  return {
    saved: false,
    conflict: false,
    message: `${mapped.title}. ${mapped.message}`,
  }
}
