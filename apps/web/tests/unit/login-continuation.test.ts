import { describe, expect, it } from 'vitest'

import {
  VERIFICATION_RESEND_MESSAGE,
  VERIFICATION_RESEND_RATE_LIMIT,
  loginContinuation,
  resendVerificationResult,
} from '@/lib/login-continuation'

describe('loginContinuation', () => {
  it('keeps an enrollment-only sign-in off the application', () => {
    expect(
      loginContinuation(200, {
        user: { id: 2 },
        workspace_id: 9,
        requires_mfa_enrol: true,
      })
    ).toEqual({ kind: 'mfa-enrol' })
  })

  it('still sends a normal sign-in into the application', () => {
    expect(
      loginContinuation(200, { user: { id: 2 }, workspace_id: 9 })
    ).toEqual({ kind: 'app' })
  })

  it('prefers a two-factor challenge over enrollment', () => {
    expect(
      loginContinuation(200, {
        requires_mfa: true,
        mfa_token: 'synthetic-challenge',
        requires_mfa_enrol: true,
      })
    ).toEqual({ kind: 'mfa-challenge' })
  })

  it('shows the administrator-reset message from the login error', () => {
    expect(
      loginContinuation(403, {
        detail:
          'An administrator must reset multi-factor authentication before you can sign in.',
        error: { code: 'mfa_reset_required' },
      })
    ).toEqual({
      kind: 'failed',
      message:
        'An administrator must reset multi-factor authentication before you can sign in.',
    })
  })

  it('keeps the existing rate-limit and onboarding branches', () => {
    expect(loginContinuation(429, {})).toEqual({ kind: 'rate-limited' })
    expect(loginContinuation(200, { needs_onboarding: true })).toEqual({
      kind: 'onboarding',
    })
  })

  it('shows a resend action when the account is not verified', () => {
    expect(
      loginContinuation(403, {
        detail: 'Verify your email before signing in.',
        error: { code: 'email_not_verified' },
      })
    ).toEqual({
      kind: 'email-not-verified',
      message: 'Verify your email before signing in.',
    })
  })

  it('shows the generic resend reply, including when the body is empty', () => {
    expect(
      resendVerificationResult(200, { message: VERIFICATION_RESEND_MESSAGE })
    ).toEqual({ kind: 'sent', message: VERIFICATION_RESEND_MESSAGE })
    expect(resendVerificationResult(200, {})).toEqual({
      kind: 'sent',
      message: VERIFICATION_RESEND_MESSAGE,
    })
  })

  it('shows a rate-limit message when another verification email is refused', () => {
    expect(
      resendVerificationResult(429, { detail: 'Too many requests' })
    ).toEqual({
      kind: 'rate-limited',
      message: VERIFICATION_RESEND_RATE_LIMIT,
    })
  })
})
