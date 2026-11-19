'use client'

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { useRouter } from 'next/navigation'
import type { AuthState, MeResponse } from '@/lib/auth-types'
import { presentHttpFailure } from '@/lib/api-error'

const initialState: AuthState = {
  user: null,
  workspace: null,
  workspaces: [],
  permissions: {
    can_edit: false,
    can_review: false,
    can_admin: false,
    can_export: false,
  },
  loading: true,
  error: null,
  failure: null,
  requestId: 0,
}

const AuthContext = createContext<
  AuthState & {
    refresh: () => Promise<void>
    switchWorkspace: (workspaceId: number) => Promise<boolean>
  }
>({
  ...initialState,
  refresh: async () => {},
  switchWorkspace: async () => false,
})

function parseMe(data: MeResponse): AuthState {
  return {
    user: { id: data.id, email: data.email, display_name: data.display_name },
    workspace: {
      id: data.workspace_id,
      name: data.workspace_name,
      slug: data.workspace_slug,
      role: data.role,
    },
    workspaces: data.workspaces ?? [],
    permissions: data.permissions ?? {
      can_edit: false,
      can_review: false,
      can_admin: false,
      can_export: false,
    },
    loading: false,
    error: null,
    failure: null,
    requestId: 0,
    needs_onboarding: data.needs_onboarding,
    subscription: data.subscription,
    mfa_enrolled: data.mfa_enrolled,
    mfa_required_for_workspace: data.mfa_required_for_workspace,
    workspace_auth_policy: data.workspace_auth_policy,
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [state, setState] = useState<AuthState>(initialState)

  const pull = useCallback(() => {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 15000)
    return fetch('/api/auth/me', {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(async (res) => {
        clearTimeout(timeoutId)
        if (!res.ok) {
          const failure =
            res.status === 401
              ? null
              : presentHttpFailure({ status: res.status })
          setState((s) => ({
            ...s,
            user: null,
            workspace: null,
            workspaces: [],
            loading: false,
            error: failure ? failure.title : null,
            failure,
          }))
          return
        }
        let data: MeResponse
        try {
          data = (await res.json()) as MeResponse
        } catch {
          const failure = presentHttpFailure({ malformed: true })
          setState((s) => ({
            ...s,
            user: null,
            workspace: null,
            workspaces: [],
            loading: false,
            error: failure.title,
            failure,
          }))
          return
        }
        setState((s) => ({ ...parseMe(data), requestId: s.requestId }))
      })
      .catch(() => {
        clearTimeout(timeoutId)
        const failure = presentHttpFailure({ offline: true })
        setState((s) => ({
          ...s,
          loading: false,
          error: failure.title,
          failure,
        }))
      })
  }, [])

  const refresh = useCallback(() => {
    setState((s) => ({
      ...s,
      loading: true,
      error: null,
      failure: null,
      requestId: s.requestId + 1,
    }))
    return pull()
  }, [pull])

  const switchWorkspace = useCallback(
    async (workspaceId: number): Promise<boolean> => {
      try {
        const res = await fetch('/api/auth/switch-workspace', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ workspace_id: workspaceId }),
        })
        if (!res.ok) return false
        let data: Record<string, unknown> | null = null
        try {
          data = (await res.json()) as Record<string, unknown>
        } catch {
          data = null
        }
        // A challenge does not change the cookie. Do not adopt the target role
        // or keep the previous workspace's MFA flag as if the switch landed.
        if (data?.requires_mfa === true) {
          const token = data.mfa_token
          if (typeof token === 'string' && token.length > 0) {
            router.push(`/login?mfa_token=${encodeURIComponent(token)}`)
          }
          return false
        }
        await pull()
        return true
      } catch {
        return false
      }
    },
    [pull, router]
  )

  useEffect(() => {
    void pull()
  }, [pull])

  return (
    <AuthContext.Provider value={{ ...state, refresh, switchWorkspace }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
