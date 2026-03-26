'use client'

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { AuthState, MeResponse } from '@/lib/auth-types'

const initialState: AuthState = {
  user: null,
  workspace: null,
  workspaces: [],
  permissions: { can_edit: false, can_review: false, can_admin: false, can_export: false },
  loading: true,
  error: null,
}

const AuthContext = createContext<AuthState & { refresh: () => Promise<void>; switchWorkspace: (workspaceId: number) => Promise<boolean> }>({
  ...initialState,
  refresh: async () => {},
  switchWorkspace: async () => false,
})

function parseMe(data: MeResponse): AuthState {
  return {
    user: { id: data.id, email: data.email, display_name: data.display_name },
    workspace: { id: data.workspace_id, name: data.workspace_name, slug: data.workspace_slug, role: data.role },
    workspaces: data.workspaces ?? [],
    permissions: data.permissions ?? { can_edit: false, can_review: false, can_admin: false, can_export: false },
    loading: false,
    error: null,
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
    setState((s) => ({ ...s, loading: true, error: null }))
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 15000)
    try {
      const res = await fetch('/api/auth/me', { credentials: 'include', signal: controller.signal })
      clearTimeout(timeoutId)
      if (!res.ok) {
        setState((s) => ({ ...s, user: null, workspace: null, workspaces: [], loading: false, error: res.status === 401 ? null : 'Failed to load session' }))
        return
      }
      const data: MeResponse = await res.json()
      setState(parseMe(data))
    } catch {
      clearTimeout(timeoutId)
      setState((s) => ({ ...s, loading: false, error: 'Failed to load session' }))
    }
  }, [])

  const switchWorkspace = useCallback(async (workspaceId: number): Promise<boolean> => {
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
        workspace: { id: data.workspace_id, name: data.workspace_name, slug: data.workspace_slug, role: data.role },
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
  }, [])

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
