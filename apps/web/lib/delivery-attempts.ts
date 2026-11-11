/** Strict reader for GET /api/notifications/delivery-attempts. Schema version 1. */

export const DELIVERY_ATTEMPTS_SCHEMA_VERSION = 1

export const DELIVERY_ATTEMPTS_PATH = '/api/notifications/delivery-attempts'

export const DELIVERY_ATTEMPT_STATES = [
  'queued',
  'sent',
  'retrying',
  'deduped',
  'dead-lettered',
  'suppressed-by-preference',
] as const

export const DELIVERY_ATTEMPT_CHANNELS = ['email', 'slack', 'in_app'] as const

export type DeliveryAttemptState = (typeof DELIVERY_ATTEMPT_STATES)[number]
export type DeliveryAttemptChannel = (typeof DELIVERY_ATTEMPT_CHANNELS)[number]

export type DeliveryAttemptView = {
  id: number
  channel: DeliveryAttemptChannel
  event_type: string
  template_key: string | null
  destination: string | null
  state: DeliveryAttemptState
  attempt_number: number
  max_attempts: number
  error_code: string | null
  claimed: boolean
  is_read: boolean | null
  created_at: string | null
}

export type DeliveryAttemptsPage = {
  schema_version: typeof DELIVERY_ATTEMPTS_SCHEMA_VERSION
  total: number
  page: number
  attempts: DeliveryAttemptView[]
}

export type DeliveryAttemptDisplay = {
  channel: string
  template: string
  event: string
  destination: string
  state: string
  claimed: boolean
  attempts: string
  read: string
}

const UNSAFE_TEXT =
  /xox[baprs]-|sk_(?:live|test)_|\bBearer\s+\S+|PRIVATE KEY|\bsource\s+quote\b|\bevidence\s*[:=]/i

function malformed(detail: string): never {
  throw new Error(`delivery attempts response is malformed: ${detail}`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (
    typeof value !== 'number' ||
    !Number.isSafeInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    malformed('integer')
  }
  return value
}

function nullableInteger(
  value: unknown,
  minimum: number,
  maximum: number
): number | null {
  if (value === null) return null
  return integer(value, minimum, maximum)
}

function safeText(
  value: unknown,
  maximum: number,
  required: boolean
): string | null {
  if (value === null) {
    if (required) malformed('text')
    return null
  }
  if (typeof value !== 'string') malformed('text')
  const text = value
  if (required && text.length === 0) malformed('text')
  if (text.length > maximum) malformed('text')
  if (UNSAFE_TEXT.test(text)) malformed('unsafe text')
  return text
}

function optionalStoredText(value: unknown, maximum: number): void {
  if (value === null) return
  if (typeof value !== 'string' || value.length > maximum)
    malformed('stored text')
}

function timestamp(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || value.length === 0 || value.length > 40) {
    malformed('timestamp')
  }
  if (UNSAFE_TEXT.test(value)) malformed('unsafe text')
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(
      value
    )
  ) {
    malformed('timestamp')
  }
  return value
}

function oneAttempt(value: unknown): DeliveryAttemptView {
  if (!isRecord(value)) malformed('attempt')
  const channel = safeText(value.channel, 16, true)
  if (channel !== 'email' && channel !== 'slack' && channel !== 'in_app') {
    malformed('channel')
  }
  const state = safeText(value.state, 32, true)
  if (!DELIVERY_ATTEMPT_STATES.includes(state as DeliveryAttemptState)) {
    malformed('state')
  }
  if (typeof value.delivered_to_provider !== 'boolean')
    malformed('provider flag')
  optionalStoredText(value.recipient, 255)
  if (typeof value.recipient !== 'string' || value.recipient.length === 0) {
    malformed('recipient')
  }
  optionalStoredText(value.dedupe_key, 512)
  if (typeof value.dedupe_key !== 'string' || value.dedupe_key.length === 0) {
    malformed('dedupe key')
  }
  optionalStoredText(value.provider_mode, 32)
  if (value.provider_mode !== null && typeof value.provider_mode !== 'string') {
    malformed('provider mode')
  }
  optionalStoredText(value.rendered_subject, 512)
  optionalStoredText(value.rendered_body, 2000)
  optionalStoredText(value.error, 2000)
  void nullableInteger(value.user_id, 1, 2147483647)
  const errorCode = safeText(value.error_code, 64, false)
  let isRead: boolean | null
  if (value.is_read === null) isRead = null
  else if (typeof value.is_read === 'boolean') isRead = value.is_read
  else malformed('read state')
  const inAppId = nullableInteger(value.in_app_notification_id, 1, 2147483647)
  if ((isRead === null) !== (inAppId === null)) malformed('read state')
  const templateKey = safeText(value.template_key, 96, false)
  return {
    id: integer(value.id, 1, 2147483647),
    channel,
    event_type: safeText(value.event_type, 64, true) as string,
    template_key: templateKey,
    destination: safeText(value.destination, 255, false),
    state: state as DeliveryAttemptState,
    attempt_number: integer(value.attempt_number, 0, 100),
    max_attempts: integer(value.max_attempts, 1, 100),
    error_code: errorCode,
    claimed: errorCode === 'claimed',
    is_read: isRead,
    created_at: timestamp(value.created_at),
  }
}

export function parseDeliveryAttempts(body: unknown): DeliveryAttemptsPage {
  if (!isRecord(body)) malformed('body')
  if (body.schema_version !== DELIVERY_ATTEMPTS_SCHEMA_VERSION) {
    malformed('schema')
  }
  if (!Array.isArray(body.attempts)) malformed('attempts')
  const total = integer(body.total, 0, 2147483647)
  const page = integer(body.page, 1, 2147483647)
  if (body.attempts.length > total) malformed('total')
  const attempts = body.attempts.map((item) => oneAttempt(item))
  const ids = new Set(attempts.map((item) => item.id))
  if (ids.size !== attempts.length) malformed('id')
  return {
    schema_version: DELIVERY_ATTEMPTS_SCHEMA_VERSION,
    total,
    page,
    attempts,
  }
}

/** Same contract the API test runs. The returned object has no message body. */
export function acceptDeliveryAttemptsContract(
  body: unknown
): DeliveryAttemptsPage {
  return parseDeliveryAttempts(body)
}

export function displayDeliveryAttempt(
  attempt: DeliveryAttemptView
): DeliveryAttemptDisplay {
  return {
    channel: attempt.channel,
    template: attempt.template_key ?? attempt.event_type,
    event: attempt.event_type,
    destination: attempt.destination ?? '—',
    state: attempt.state,
    claimed: attempt.claimed,
    attempts: String(attempt.attempt_number),
    read:
      attempt.is_read === true
        ? 'Read'
        : attempt.is_read === false
          ? 'Unread'
          : 'No in-app message',
  }
}
