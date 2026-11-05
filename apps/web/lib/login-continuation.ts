import { formatApiErrorDetail } from '@/lib/api-error'

export type LoginContinuation =
  | { kind: 'mfa-challenge' }
  | { kind: 'mfa-enrol' }
  | { kind: 'rate-limited' }
  | { kind: 'failed'; message: string }
  | { kind: 'onboarding' }
  | { kind: 'app' }

/**
 * Decide what the sign-in page does with a login response.
 * An enrollment-only session must stay on this page: that cookie cannot open the app.
 */
export function loginContinuation(
  status: number,
  data: unknown
): LoginContinuation {
  const rec =
    data && typeof data === 'object' ? (data as Record<string, unknown>) : {}
  if (
    rec.requires_mfa === true &&
    typeof rec.mfa_token === 'string' &&
    rec.mfa_token.length > 0
  ) {
    return { kind: 'mfa-challenge' }
  }
  if (status === 429) return { kind: 'rate-limited' }
  if (status < 200 || status >= 300) {
    return {
      kind: 'failed',
      message: formatApiErrorDetail(data, `Login failed (${status})`),
    }
  }
  if (rec.needs_onboarding === true) return { kind: 'onboarding' }
  if (rec.requires_mfa_enrol === true) return { kind: 'mfa-enrol' }
  return { kind: 'app' }
}
