import { formatApiErrorDetail } from '@/lib/api-error'

export const VERIFICATION_RESEND_MESSAGE =
  'If that email is waiting for verification, a new message is on the way.'

export const VERIFICATION_RESEND_RATE_LIMIT =
  'Too many verification emails. Try again later.'

export type LoginContinuation =
  | { kind: 'mfa-challenge' }
  | { kind: 'mfa-enrol' }
  | { kind: 'rate-limited' }
  | { kind: 'email-not-verified'; message: string }
  | { kind: 'failed'; message: string }
  | { kind: 'onboarding' }
  | { kind: 'app' }

export type ResendVerificationResult =
  | { kind: 'sent'; message: string }
  | { kind: 'rate-limited'; message: string }
  | { kind: 'failed'; message: string }

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
    const error = rec.error
    const code =
      error && typeof error === 'object'
        ? (error as Record<string, unknown>).code
        : undefined
    if (status === 403 && code === 'email_not_verified') {
      return {
        kind: 'email-not-verified',
        message: formatApiErrorDetail(
          data,
          'Verify your email before signing in.'
        ),
      }
    }
    return {
      kind: 'failed',
      message: formatApiErrorDetail(data, `Login failed (${status})`),
    }
  }
  if (rec.needs_onboarding === true) return { kind: 'onboarding' }
  if (rec.requires_mfa_enrol === true) return { kind: 'mfa-enrol' }
  return { kind: 'app' }
}

/** What the sign-in and register pages show after asking for another verification email. */
export function resendVerificationResult(
  status: number,
  data: unknown
): ResendVerificationResult {
  if (status === 429) {
    return { kind: 'rate-limited', message: VERIFICATION_RESEND_RATE_LIMIT }
  }
  if (status >= 200 && status < 300) {
    const rec =
      data && typeof data === 'object' ? (data as Record<string, unknown>) : {}
    const message =
      typeof rec.message === 'string' && rec.message.trim()
        ? rec.message
        : VERIFICATION_RESEND_MESSAGE
    return { kind: 'sent', message }
  }
  return {
    kind: 'failed',
    message: formatApiErrorDetail(data, 'Could not send a verification email'),
  }
}

export async function requestVerificationEmail(
  email: string
): Promise<ResendVerificationResult> {
  try {
    const response = await fetch('/api/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    const data = await response.json().catch(() => ({}))
    return resendVerificationResult(response.status, data)
  } catch {
    return { kind: 'failed', message: 'Network error. Please try again.' }
  }
}
