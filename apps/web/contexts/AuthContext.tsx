'use client'

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
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
  const [state, setState] = useState<AuthState>(initialState)

  const refresh = useCallback(async () => {
    setState((s) => ({
      ...s,
      loading: true,
      error: null,
      failure: null,
      requestId: s.requestId + 1,
    }))
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 15000)
    try {
      const res = await fetch('/api/auth/me', {
        credentials: 'include',
        signal: controller.signal,
      })
      clearTimeout(timeoutId)
      if (!res.ok) {
        const failure =
          res.status === 401 ? null : presentHttpFailure({ status: res.status })
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
    } catch {
      clearTimeout(timeoutId)
      const failure = presentHttpFailure({ offline: true })
      setState((s) => ({
        ...s,
        loading: false,
        error: failure.title,
        failure,
      }))
    }
  }, [])

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
        const data = await res.json()
        setState((s) => ({
          ...s,
          workspace: {
            id: data.workspace_id,
            name: data.workspace_name,
            slug: data.workspace_slug,
            role: data.role,
          },
          permissions: {
            can_edit: ['admin', 'editor'].includes(data.role),
            can_review: ['admin', 'editor', 'reviewer'].includes(data.role),
            can_admin: data.role === 'admin',
            can_export: ['admin', 'editor'].includes(data.role),
          },
        }))
        return true
      } catch {
        return false
      }
    },
    []
  )

  useEffect(() => {
    refresh()
  }, [refresh])

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
