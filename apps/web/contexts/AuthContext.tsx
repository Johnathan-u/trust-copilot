'use client'

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
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
  session_expiry: null,
  session_expiry_status: 'checking',
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

  const mounted = useRef(false)
  const sequence = useRef(0)
  const switchTarget = useRef<number | null>(null)
  const pending = useRef<{
    controller: AbortController
    timeout: ReturnType<typeof setTimeout>
  } | null>(null)

  const cancelPending = useCallback(() => {
    sequence.current += 1
    if (pending.current) {
      clearTimeout(pending.current.timeout)
      pending.current.controller.abort()
      pending.current = null
    }
  }, [])

  const pull = useCallback(async () => {
    if (!mounted.current) return false
    cancelPending()
    const request = sequence.current
    const current = () => mounted.current && request === sequence.current
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    pending.current = { controller, timeout }
    const started = performance.now()
    setState((s) => ({
      ...s,
      session_expiry: null,
      session_expiry_status: 'checking',
    }))
    try {
      const res = await fetch('/api/auth/me', {
        credentials: 'include',
        cache: 'no-store',
        signal: controller.signal,
      })
      if (!current()) return false
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
          session_expiry: null,
          session_expiry_status: 'unavailable',
        }))
        return false
      }
      let data: MeResponse
      try {
        data = (await res.json()) as MeResponse
        // Every retry must confirm the acknowledged workspace before exposing
        // a principal again, including refreshes that supersede the switch read.
        if (
          switchTarget.current !== null &&
          (!data ||
            !Number.isSafeInteger(data.id) ||
            data.id <= 0 ||
            typeof data.email !== 'string' ||
            typeof data.display_name !== 'string' ||
            data.workspace_id !== switchTarget.current ||
            typeof data.workspace_name !== 'string' ||
            typeof data.role !== 'string')
        ) {
          throw new Error('Invalid workspace confirmation')
        }
      } catch {
        if (!current()) return false
        const failure = presentHttpFailure({ malformed: true })
        setState((s) => ({
          ...s,
          user: null,
          workspace: null,
          workspaces: [],
          loading: false,
          error: failure.title,
          failure,
          session_expiry: null,
          session_expiry_status: 'unavailable',
        }))
        return false
      }
      if (!current()) return false
      switchTarget.current = null
      // Deduct the whole request duration conservatively. Wall-clock skew must
      // never add time to the server's enforced absolute deadline.
      const expiry = data.session_expires_at
      const serverTime = data.server_time
      const deadline =
        typeof expiry === 'number' && typeof serverTime === 'number'
          ? started + (expiry - serverTime) * 1000
          : Number.NaN
      const timing =
        typeof expiry === 'number' &&
        expiry > 0 &&
        typeof serverTime === 'number' &&
        Number.isFinite(expiry) &&
        Number.isFinite(serverTime) &&
        serverTime > 0 &&
        Number.isFinite(deadline)
          ? {
              expires_at: expiry,
              deadline,
              // Receipt is the latest possible server observation. Recheck at
              // this upper bound so an early display cannot strand an expired
              // session after a still-valid response just before server expiry.
              check_at:
                performance.now() + Math.max(0, (expiry - serverTime) * 1000),
            }
          : null
      setState((s) => ({
        ...parseMe(data),
        requestId: s.requestId,
        session_expiry: timing,
        session_expiry_status: timing ? 'ready' : 'unavailable',
      }))
      return true
    } catch {
      if (!current()) return false
      const failure = presentHttpFailure({ offline: true })
      setState((s) => ({
        ...s,
        loading: false,
        error: failure.title,
        failure,
        session_expiry: null,
        session_expiry_status: 'unavailable',
      }))
      return false
    } finally {
      clearTimeout(timeout)
      if (current()) pending.current = null
    }
  }, [cancelPending])

  const refresh = useCallback(async () => {
    setState((s) => ({
      ...s,
      loading: true,
      error: null,
      failure: null,
      requestId: s.requestId + 1,
    }))
    await pull()
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
        if (!res.ok || !mounted.current) return false
        // The server has changed tenants. Withhold all previous authority until
        // /me confirms the selected workspace, even if that read fails offline.
        switchTarget.current = workspaceId
        setState((s) => ({ ...initialState, requestId: s.requestId }))
        // Read the effective policy and permissions for the newly selected
        // workspace from the same authoritative endpoint as initial loading.
        return await pull()
      } catch {
        return false
      }
    },
    [pull]
  )

  useEffect(() => {
    mounted.current = true
    const startup = sequence.current
    void Promise.resolve().then(() => {
      if (mounted.current && startup === sequence.current) void pull()
    })
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void pull()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      mounted.current = false
      cancelPending()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [cancelPending, pull])

  useEffect(() => {
    const timing = state.session_expiry
    if (!timing) return
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      const remaining = timing.check_at - performance.now()
      if (remaining <= 0) {
        if (document.visibilityState === 'visible') void pull()
        return
      }
      // Browsers overflow larger timeout delays (for example 90-day policies).
      timer = setTimeout(schedule, Math.min(remaining, 2_147_483_647))
    }
    schedule()
    return () => clearTimeout(timer)
  }, [state.session_expiry, pull])

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
