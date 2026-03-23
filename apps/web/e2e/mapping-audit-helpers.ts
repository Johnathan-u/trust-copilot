/**
 * Shared helpers for questionnaire mapping / compliance audit E2E specs.
 */
import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const DEMO_EMAIL = 'demo@trust.local'
export const DEMO_PASSWORD = 'j'
export const ADMIN_EMAIL = 'admin@trust.local'
export const ADMIN_PASSWORD = 'Admin123!'

export type ParsedQuestionnairePick = {
  id: number
  filename: string
  questionCount: number
  cloudSecurityHint: boolean
}

export async function loginDemo(page: Page) {
  await page.goto('/login', { waitUntil: 'load' })
  await page.locator('input[type="email"]').waitFor({ state: 'visible' })
  await page.locator('input[type="password"]').waitFor({ state: 'visible' })
  await page.locator('input[type="email"]').click()
  await page.locator('input[type="email"]').fill('')
  await page.locator('input[type="email"]').pressSequentially(DEMO_EMAIL, { delay: 5 })
  await page.locator('input[type="password"]').click()
  await page.locator('input[type="password"]').fill('')
  await page.locator('input[type="password"]').pressSequentially(DEMO_PASSWORD, { delay: 5 })
  const signIn = page.getByRole('button', { name: 'Sign in' })
  await signIn.waitFor({ state: 'visible' })
  await expect(signIn).toBeEnabled({ timeout: 60_000 })
  await signIn.click()
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 120_000 })
}

export async function ensureAuthenticated(page: Page) {
  if (process.env.E2E_SERVER_RUNNING) {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 })
  } else {
    await loginDemo(page)
  }
}

export async function getWorkspaceId(request: APIRequestContext): Promise<number> {
  const meRes = await request.get('/api/auth/me')
  expect(meRes.ok()).toBeTruthy()
  const me = (await meRes.json()) as { workspace_id: number }
  return me.workspace_id
}

/** Prefer largest parsed questionnaire; boost score if filename suggests cloud/security vendor questionnaire. */
export async function pickBestParsedQuestionnaire(
  request: APIRequestContext,
  workspaceId: number,
): Promise<ParsedQuestionnairePick | null> {
  const qnrRes = await request.get(`/api/questionnaires/?workspace_id=${workspaceId}`)
  expect(qnrRes.ok()).toBeTruthy()
  const qnrs = (await qnrRes.json()) as { id: number; status: string; filename: string; deleted_at?: string | null }[]
  const parsed = qnrs.filter((q) => q.status === 'parsed' && !q.deleted_at)
  if (parsed.length === 0) return null

  let best: ParsedQuestionnairePick | null = null
  let bestScore = -1

  for (const q of parsed) {
    const detRes = await request.get(`/api/questionnaires/${q.id}?workspace_id=${workspaceId}`)
    if (!detRes.ok()) continue
    const det = (await detRes.json()) as { questions?: unknown[] }
    const n = Array.isArray(det.questions) ? det.questions.length : 0
    if (n === 0) continue
    const name = (q.filename || '').toLowerCase()
    const cloudSecurityHint = /cloud|security|soc|vendor|assessment|due diligence|cia|cisa|nist/.test(name)
    const score = n * 10 + (cloudSecurityHint ? 500 : 0)
    if (score > bestScore) {
      bestScore = score
      best = { id: q.id, filename: q.filename, questionCount: n, cloudSecurityHint }
    }
  }
  return best
}

/** Playwright's TS types for APIRequestContext may omit `json`; use explicit JSON body. */
export function jsonRequest(body: unknown): { data: string; headers: Record<string, string> } {
  return {
    data: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  }
}

export async function postJsonLogin(request: APIRequestContext, email: string, password: string) {
  const res = await request.post('/api/auth/login', {
    ...jsonRequest({ email, password, remember_me: false }),
  })
  expect(res.ok(), `login failed ${email}: ${await res.text()}`).toBeTruthy()
}

/** Reset all mappings for a questionnaire to suggested (clean slate for tests). */
export async function resetMappingsToSuggested(
  request: APIRequestContext,
  workspaceId: number,
  questionnaireId: number,
) {
  const existingRes = await request.get(
    `/api/questionnaires/${questionnaireId}/mappings?workspace_id=${workspaceId}`,
  )
  if (!existingRes.ok()) return
  const body = (await existingRes.json()) as { mappings?: { id: number }[] }
  for (const m of body.mappings || []) {
    await request.patch(`/api/questionnaires/${questionnaireId}/mappings/${m.id}?workspace_id=${workspaceId}`, {
      ...jsonRequest({ status: 'suggested' }),
    })
  }
}

export const BENCHMARK_TERMS = [
  'least privilege',
  'mfa',
  'multi-factor',
  'admin access',
  'encryption in transit',
  'tls',
  'encryption at rest',
  'log retention',
  'incident response',
  'backup',
  'recovery',
] as const

export const CLOUD_AUDIT_TERMS = [
  'least privilege',
  'transit',
  'tls',
  'at rest',
  'backup',
  'recover',
  'kubernetes',
  'rbac',
  'siem',
  'logging',
  'secret',
  'kms',
  'ci/cd',
  'change management',
] as const
