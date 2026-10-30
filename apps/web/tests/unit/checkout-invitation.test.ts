// @vitest-environment happy-dom

import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CheckoutPage from '@/app/checkout/page'
import { resetWorkspaceCreationPolicyForTests } from '@/lib/workspace-creation-policy'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}))

const invitationCopy =
  'Access is set up by invitation. Ask your workspace administrator for an invite.'
const requests: string[] = []

beforeEach(() => {
  requests.length = 0
  resetWorkspaceCreationPolicyForTests()
  vi.stubGlobal('fetch', async (input: RequestInfo | URL) => {
    requests.push(String(input))
    return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    })
  })
})

afterEach(() => {
  cleanup()
  resetWorkspaceCreationPolicyForTests()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('anonymous checkout invitation', () => {
  it.each([
    [
      'owner.contact@example.com',
      'mailto:owner.contact@example.com?subject=Workspace%20access',
    ],
    ['https://example.com/contact', 'https://example.com/contact'],
  ])(
    'keeps configured contact %s without an authenticated policy read',
    async (contact, href) => {
      vi.stubEnv('NEXT_PUBLIC_SALES_CONTACT', contact)

      render(createElement(CheckoutPage))
      await act(async () => {})

      expect(screen.getByText(invitationCopy)).toBeTruthy()
      expect(
        screen.getByRole('link', { name: 'Contact sales' }).getAttribute('href')
      ).toBe(href)
      expect(
        screen.getByRole('link', { name: 'Back' }).getAttribute('href')
      ).toBe('/pricing')
      expect(document.activeElement).toBe(
        screen.getByTestId('workspace-invitation-notice')
      )
      expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
      expect(
        screen.queryByRole('button', { name: 'Create workspace' })
      ).toBeNull()
      expect(document.querySelector('form')).toBeNull()
      expect(document.querySelector('input')).toBeNull()
      expect(requests).toEqual([])
    }
  )

  it('keeps invitation and back navigation when no contact is configured', async () => {
    vi.stubEnv('NEXT_PUBLIC_SALES_CONTACT', '')

    render(createElement(CheckoutPage))
    await act(async () => {})

    expect(screen.getByText(invitationCopy)).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Contact sales' })).toBeNull()
    expect(
      screen.getByRole('link', { name: 'Back' }).getAttribute('href')
    ).toBe('/pricing')
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(document.querySelector('form')).toBeNull()
    expect(requests).toEqual([])
  })
})
