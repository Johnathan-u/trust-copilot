/** Auth types aligned with GET /api/auth/me and switch-workspace (AUTH-203, WEB-201). */

export interface AuthUser {
  id: number
  email: string
  display_name: string
}

export interface AuthWorkspace {
  id: number
  name: string
  slug?: string
  role: string
}

export interface AuthPermissions {
  can_edit: boolean
  can_review: boolean
  can_admin: boolean
  can_export: boolean
}

export interface AuthState {
  user: AuthUser | null
  workspace: AuthWorkspace | null
  workspaces: AuthWorkspace[]
  permissions: AuthPermissions
  loading: boolean
  error: string | null
  mfa_enrolled?: boolean
  mfa_required_for_workspace?: boolean
  workspace_auth_policy?: { mfa_required: boolean; session_max_age_seconds: number | null }
}

export interface MeResponse {
  id: number
  email: string
  display_name: string
  workspace_id: number
  workspace_name: string
  workspace_slug?: string
  role: string
  workspaces: { id: number; name: string; slug?: string; role: string }[]
  permissions: AuthPermissions
  mfa_enrolled?: boolean
  mfa_required_for_workspace?: boolean
  workspace_auth_policy?: { mfa_required: boolean; session_max_age_seconds: number | null }
}
