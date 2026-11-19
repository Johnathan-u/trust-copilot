// @vitest-environment happy-dom

import { createElement, type ReactNode } from 'react'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const navigation = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: navigation.push }),
}))

import { AuthProvider, useAuth } from '@/contexts/AuthContext'

function meBody(flag: boolean, role = 'reviewer', workspaceId = 1) {
  return {
    id: 4,
    email: 'switch-mfa@example.test',
    display_name: 'Switch MFA',
    workspace_id: workspaceId,
    workspace_name: workspaceId === 1 ? 'Open' : 'Required',
    workspace_slug: workspaceId === 1 ? 'open' : 'required',
    role,
    workspaces: [
      { id: 1, name: 'Open', slug: 'open', role: 'reviewer' },
      { id: 2, name: 'Required', slug: 'required', role: 'admin' },
    ],
    permissions: {
      can_edit: role === 'admin' || role === 'editor',
      can_review: role !== 'mfa_enrol',
      can_admin: role === 'admin',
      can_export: role === 'admin' || role === 'editor',
    },
    mfa_enrolled: role !== 'mfa_enrol',
    mfa_required_for_workspace: flag,
    workspace_auth_policy: {
      mfa_required: flag,
      session_max_age_seconds: null,
    },
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function installFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response>
) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      handler(String(input), init)
    )
  )
}

async function mount() {
  const rendered = renderHook(() => useAuth(), {
    wrapper: ({ children }: { children: ReactNode }) =>
      createElement(AuthProvider, null, children),
  })
  await waitFor(() => expect(rendered.result.current.loading).toBe(false))
  return rendered
}

describe('switchWorkspace MFA flag', () => {
  it('refreshes mfa_required_for_workspace from the current session after a switch', async () => {
    let flag = false
    let role = 'reviewer'
    let workspaceId = 1
    installFetch(async (url, init) => {
      if (url === '/api/auth/me') {
        return Response.json(meBody(flag, role, workspaceId))
      }
      if (url === '/api/auth/switch-workspace' && init?.method === 'POST') {
        flag = true
        role = 'admin'
        workspaceId = 2
        return Response.json({
          workspace_id: 2,
          workspace_name: 'Required',
          workspace_slug: 'required',
          role: 'admin',
        })
      }
      throw new Error(`Unexpected fetch ${init?.method ?? 'GET'} ${url}`)
    })
    const rendered = await mount()
    expect(rendered.result.current.mfa_required_for_workspace).toBe(false)

    await act(async () => {
      expect(await rendered.result.current.switchWorkspace(2)).toBe(true)
    })

    expect(rendered.result.current.mfa_required_for_workspace).toBe(true)
    expect(rendered.result.current.workspace?.id).toBe(2)
    expect(rendered.result.current.workspace?.role).toBe('admin')
  })

  it('clears a stale requirement when the switched workspace does not require MFA', async () => {
    let flag = true
    installFetch(async (url, init) => {
      if (url === '/api/auth/me') {
        return Response.json(meBody(flag, 'editor', flag ? 2 : 1))
      }
      if (url === '/api/auth/switch-workspace' && init?.method === 'POST') {
        flag = false
        return Response.json({
          workspace_id: 1,
          workspace_name: 'Open',
          role: 'editor',
        })
      }
      throw new Error(`Unexpected fetch ${init?.method ?? 'GET'} ${url}`)
    })
    const rendered = await mount()
    expect(rendered.result.current.mfa_required_for_workspace).toBe(true)

    await act(async () => {
      expect(await rendered.result.current.switchWorkspace(1)).toBe(true)
    })

    expect(rendered.result.current.mfa_required_for_workspace).toBe(false)
    expect(rendered.result.current.workspace?.role).toBe('editor')
  })

  it('adopts the enrol-only session flag after a switch', async () => {
    let enrol = false
    installFetch(async (url, init) => {
      if (url === '/api/auth/me') {
        return Response.json(
          meBody(enrol, enrol ? 'mfa_enrol' : 'reviewer', enrol ? 2 : 1)
        )
      }
      if (url === '/api/auth/switch-workspace' && init?.method === 'POST') {
        enrol = true
        return Response.json({
          workspace_id: 2,
          role: 'mfa_enrol',
          requires_mfa_enrol: true,
        })
      }
      throw new Error(`Unexpected fetch ${init?.method ?? 'GET'} ${url}`)
    })
    const rendered = await mount()

    await act(async () => {
      expect(await rendered.result.current.switchWorkspace(2)).toBe(true)
    })

    expect(rendered.result.current.mfa_required_for_workspace).toBe(true)
    expect(rendered.result.current.workspace?.role).toBe('mfa_enrol')
    expect(rendered.result.current.permissions.can_admin).toBe(false)
  })

  it('does not adopt the target role when the switch requires a fresh challenge', async () => {
    navigation.push.mockClear()
    installFetch(async (url, init) => {
      if (url === '/api/auth/me') return Response.json(meBody(false))
      if (url === '/api/auth/switch-workspace' && init?.method === 'POST') {
        return Response.json({
          requires_mfa: true,
          mfa_token: 'synthetic-challenge-token-value-0123456789',
          role: 'admin',
          workspace_id: 2,
          mfa_required_for_workspace: true,
        })
      }
      throw new Error(`Unexpected fetch ${init?.method ?? 'GET'} ${url}`)
    })
    const rendered = await mount()

    await act(async () => {
      expect(await rendered.result.current.switchWorkspace(2)).toBe(false)
    })

    expect(rendered.result.current.workspace?.id).toBe(1)
    expect(rendered.result.current.workspace?.role).toBe('reviewer')
    expect(rendered.result.current.mfa_required_for_workspace).toBe(false)
    expect(navigation.push).toHaveBeenCalledWith(
      '/login?mfa_token=synthetic-challenge-token-value-0123456789'
    )
  })
})
