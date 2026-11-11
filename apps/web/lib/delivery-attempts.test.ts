import { describe, expect, it } from 'vitest'

import {
  acceptDeliveryAttemptsContract,
  displayDeliveryAttempt,
  parseDeliveryAttempts,
  type DeliveryAttemptsPage,
} from '@/lib/delivery-attempts'

const SECRET = 'sk_live_notshown'
const SOURCE = 'source quote: private evidence'

function attempt(overrides: Record<string, unknown> = {}) {
  return {
    id: 9,
    event_type: 'member.joined',
    channel: 'email',
    recipient: 'ada@example.com',
    user_id: 4,
    state: 'dead-lettered',
    attempt_number: 3,
    max_attempts: 3,
    dedupe_key: 'a'.repeat(64),
    delivered_to_provider: false,
    provider_mode: 'fixture',
    template_key: 'member.joined:email',
    destination: 'ada@example.com',
    rendered_subject: `Member joined — ${SOURCE}`,
    rendered_body: `${SOURCE} ${SECRET}`,
    error_code: 'unknown',
    error: SECRET,
    in_app_notification_id: null,
    is_read: null,
    created_at: '2026-11-11T22:29:00.123456',
    ...overrides,
  }
}

function page(attempts: Record<string, unknown>[]): Record<string, unknown> {
  return {
    schema_version: 1,
    total: attempts.length,
    page: 1,
    attempts,
  }
}

describe('parseDeliveryAttempts', () => {
  it('accepts the API shape and drops message content', () => {
    const body = page([
      attempt(),
      attempt({
        id: 8,
        state: 'deduped',
        attempt_number: 0,
        error_code: 'claimed',
        delivered_to_provider: false,
      }),
      attempt({
        id: 7,
        channel: 'slack',
        state: 'suppressed-by-preference',
        attempt_number: 0,
        template_key: 'member.joined:slack',
        destination: 'C0123',
        error_code: null,
        provider_mode: null,
      }),
      attempt({
        id: 6,
        state: 'retrying',
        attempt_number: 1,
        channel: 'email',
      }),
      attempt({
        id: 5,
        channel: 'in_app',
        state: 'sent',
        attempt_number: 1,
        max_attempts: 1,
        template_key: 'member.joined:in_app',
        destination: 'user:4',
        delivered_to_provider: false,
        provider_mode: 'local',
        in_app_notification_id: 15,
        is_read: false,
        error_code: null,
      }),
      attempt({
        id: 4,
        channel: 'in_app',
        state: 'queued',
        attempt_number: 0,
        max_attempts: 1,
        template_key: null,
        destination: null,
        in_app_notification_id: 16,
        is_read: true,
        created_at: null,
        error_code: null,
      }),
    ])
    const parsed = parseDeliveryAttempts(body)
    expect(parsed).toEqual(acceptDeliveryAttemptsContract(body))
    expect(parsed.schema_version).toBe(1)
    expect(parsed.attempts.map((row) => row.state)).toEqual([
      'dead-lettered',
      'deduped',
      'suppressed-by-preference',
      'retrying',
      'sent',
      'queued',
    ])
    expect(parsed.attempts[1]?.claimed).toBe(true)
    expect(parsed.attempts[1]?.error_code).toBe('claimed')
    expect(parsed.attempts[4]?.is_read).toBe(false)
    expect(parsed.attempts[5]?.is_read).toBe(true)
    const encoded = JSON.stringify(parsed)
    expect(encoded).not.toContain(SECRET)
    expect(encoded).not.toContain('source quote')
    expect(encoded).not.toContain('rendered_body')
    expect(encoded).toContain('ada@example.com')
  })

  it('rejects malformed payloads', () => {
    const samples: unknown[] = [
      null,
      [],
      { schema_version: '1', total: 0, page: 1, attempts: [] },
      { schema_version: 2, total: 0, page: 1, attempts: [] },
      { schema_version: 1, total: 0, page: 1 },
      { schema_version: 1, total: 0, page: 1, attempts: {} },
      page([attempt({ state: 'claimed' })]),
      page([attempt({ attempt_number: '3' })]),
      page([attempt({ is_read: 'true' })]),
      page([attempt({ destination: SECRET })]),
      page([attempt({ id: 1.5 })]),
      page([attempt({ channel: 'sms' })]),
      page([attempt({ in_app_notification_id: 4, is_read: null })]),
      page([attempt(), attempt()]),
      { schema_version: 1, total: 0, page: 1, attempts: [attempt()] },
    ]
    for (const sample of samples) {
      expect(() => parseDeliveryAttempts(sample)).toThrow(/malformed/)
    }
  })

  it('shows channel, template, destination, state, attempts, and read state', () => {
    const parsed: DeliveryAttemptsPage = parseDeliveryAttempts(
      page([
        attempt({
          state: 'deduped',
          error_code: 'claimed',
          attempt_number: 0,
        }),
      ])
    )
    const row = parsed.attempts[0]
    expect(row).toBeDefined()
    const display = displayDeliveryAttempt(row as NonNullable<typeof row>)
    expect(display).toEqual({
      channel: 'email',
      template: 'member.joined:email',
      event: 'member.joined',
      destination: 'ada@example.com',
      state: 'deduped',
      claimed: true,
      attempts: '0',
      read: 'No in-app message',
    })
    expect(JSON.stringify(display)).not.toContain(SECRET)
    expect(JSON.stringify(display)).not.toContain(SOURCE)
  })
})
