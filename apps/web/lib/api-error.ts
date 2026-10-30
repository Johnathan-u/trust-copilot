/** Normalize FastAPI / proxy error JSON for display. */

import {
  autoDismissMs,
  liveRegionForSeverity,
  type ToastLiveRegion,
  type ToastSeverity,
} from './toast'

/**
 * API failures and denials are shown with the danger status token
 * (`--tc-danger` on `--tc-danger-surface` or a neutral surface).
 * The helper does not change the formatted message.
 */
export const API_ERROR_STATUS = 'danger' as const

export type ApiErrorStatus = typeof API_ERROR_STATUS

export function apiErrorPresentation(
  data: unknown,
  fallback = 'Request failed'
): { message: string; status: ApiErrorStatus } {
  return {
    message: formatApiErrorDetail(data, fallback),
    status: API_ERROR_STATUS,
  }
}

/**
 * Same safe message as `formatApiErrorDetail`, announced as an error toast.
 * Errors stay until the user dismisses them. The formatted string is unchanged.
 */
export function apiErrorAnnouncement(
  data: unknown,
  fallback = 'Request failed'
): {
  message: string
  severity: Extract<ToastSeverity, 'error'>
  live: ToastLiveRegion
  autoDismissMs: null
} {
  if (autoDismissMs('error') !== null)
    throw new Error('error announcements must stay until dismissed')
  return {
    message: formatApiErrorDetail(data, fallback),
    severity: 'error',
    live: liveRegionForSeverity('error'),
    autoDismissMs: null,
  }
}

export function formatApiErrorDetail(
  data: unknown,
  fallback = 'Request failed'
): string {
  if (!data || typeof data !== 'object') return fallback
  const rec = data as Record<string, unknown>
  const d = rec.detail
  if (typeof d === 'string') return d
  if (typeof rec.message === 'string' && !d) return rec.message
  if (Array.isArray(d) && d.length > 0) {
    const first = d[0]
    if (first && typeof first === 'object' && 'msg' in first) {
      const m = (first as { msg?: unknown }).msg
      if (typeof m === 'string') return m
    }
    return JSON.stringify(d)
  }
  if (d && typeof d === 'object' && 'msg' in d) {
    const m = (d as { msg?: unknown }).msg
    if (typeof m === 'string') return m
  }
  return fallback
}

/** Throw when a mutation response failed, using the API body or status text. */
export async function throwIfResponseNotOk(response: Response): Promise<void> {
  if (response.ok) return
  const data = await response.json().catch(() => null)
  const fallback = response.statusText.trim() || 'Request failed'
  throw new Error(formatApiErrorDetail(data, fallback))
}

/**
 * Neutral page-state copy for a failed read.
 * The strings do not include status codes, role names, or permission flags,
 * and they do not echo the response body.
 */
export const API_FAILURE_KINDS = [
  'offline',
  'forbidden',
  'not_found',
  'server',
  'rejected',
] as const

export type ApiFailureKind = (typeof API_FAILURE_KINDS)[number]

export interface ApiFailurePresentation {
  kind: ApiFailureKind
  title: string
  description: string
}

const FAILURE_COPY: Record<
  ApiFailureKind,
  { title: string; description: string }
> = {
  offline: {
    title: 'Offline',
    description: 'The service could not be reached. Try again.',
  },
  forbidden: {
    title: 'This section is not available',
    description: 'It cannot be opened from this account.',
  },
  not_found: {
    title: 'We could not find that',
    description: 'It may have been moved or removed.',
  },
  server: {
    title: 'Something went wrong',
    description: 'The service could not complete this request. Try again.',
  },
  rejected: {
    title: 'Could not load this',
    description: 'The request did not succeed. Try again.',
  },
}

export const MALFORMED_RESPONSE_DESCRIPTION =
  'The response could not be read. Try again.'

export function presentHttpFailure(input: {
  status?: number | null
  offline?: boolean
  malformed?: boolean
}): ApiFailurePresentation {
  if (input.offline) return { kind: 'offline', ...FAILURE_COPY.offline }
  if (input.malformed) {
    return {
      kind: 'rejected',
      title: FAILURE_COPY.rejected.title,
      description: MALFORMED_RESPONSE_DESCRIPTION,
    }
  }
  const status = input.status ?? 0
  if (status === 403) return { kind: 'forbidden', ...FAILURE_COPY.forbidden }
  if (status === 404) return { kind: 'not_found', ...FAILURE_COPY.not_found }
  if (status >= 500 && status <= 599) {
    return { kind: 'server', ...FAILURE_COPY.server }
  }
  if (status === 0) return { kind: 'offline', ...FAILURE_COPY.offline }
  return { kind: 'rejected', ...FAILURE_COPY.rejected }
}

export class ApiRequestError extends Error {
  readonly failure: ApiFailurePresentation

  constructor(failure: ApiFailurePresentation) {
    super(failure.title)
    this.name = 'ApiRequestError'
    this.failure = failure
  }
}

/**
 * Mutation failures that need their own next step.
 * Copy is fixed. It does not repeat the response body, name a role, or
 * add a cause the payload did not identify.
 */
export const ACTION_FAILURE_KINDS = [
  'unsupported_model',
  'unsupported_format',
  'no_evidence',
  'permission',
] as const

export type ActionFailureKind = (typeof ACTION_FAILURE_KINDS)[number]

export interface ActionFailurePresentation {
  kind: ActionFailureKind
  title: string
  message: string
}

const ACTION_FAILURE_COPY: Record<
  ActionFailureKind,
  { title: string; message: string }
> = {
  unsupported_model: {
    title: 'Model not available',
    message:
      'That model is not available for this request. Choose a supported model and try again.',
  },
  unsupported_format: {
    title: 'File format not supported',
    message:
      'This file format is not supported. Choose a supported format and try again.',
  },
  no_evidence: {
    title: 'No supporting evidence',
    message:
      'No eligible evidence was found for this item, so nothing was drafted. Add evidence that covers it, then try again.',
  },
  permission: {
    title: 'Action not available',
    message:
      'This account cannot complete that action. Ask someone who manages access for this workspace, then try again.',
  },
}

const MODEL_CODES = new Set(['unsupported_model', 'model_unavailable'])
const FORMAT_CODES = new Set([
  'unsupported_format',
  'unsupported_file_format',
  'extension_not_allowed',
])
const EVIDENCE_CODES = new Set(['no_evidence'])
const PERMISSION_CODES = new Set([
  'permission_denied',
  'access_denied',
  'forbidden',
  'insufficient_permissions',
])

function collectActionSignals(data: unknown): {
  codes: string[]
  texts: string[]
} {
  const codes: string[] = []
  const texts: string[] = []
  const seen = new Set<unknown>()

  const visit = (value: unknown, depth: number) => {
    if (depth > 4 || value == null) return
    if (typeof value === 'string') {
      const text = value.trim()
      if (text) texts.push(text)
      return
    }
    if (typeof value !== 'object') return
    if (seen.has(value)) return
    seen.add(value)
    if (Array.isArray(value)) {
      for (const item of value) visit(item, depth + 1)
      return
    }
    const record = value as Record<string, unknown>
    for (const key of ['code', 'error_code', 'outcome_code']) {
      const code = record[key]
      if (typeof code === 'string' && code.trim()) {
        codes.push(code.trim().toLowerCase())
      }
    }
    for (const key of [
      'detail',
      'message',
      'error',
      'error_detail',
      'outcome',
    ]) {
      if (key in record) visit(record[key], depth + 1)
    }
  }

  visit(data, 0)
  return { codes, texts }
}

function textMatches(texts: string[], pattern: RegExp): boolean {
  return texts.some((text) => pattern.test(text))
}

/**
 * Map a mutation payload onto one of the four known failures.
 * Returns null when the payload does not identify one of those cases.
 * Callers keep their own fallback for everything else.
 */
export function presentActionFailure(input: {
  status?: number | null
  data?: unknown
}): ActionFailurePresentation | null {
  const { codes, texts } = collectActionSignals(input.data)
  const hasCode = (set: Set<string>) => codes.some((code) => set.has(code))
  let kind: ActionFailureKind | null = null
  if (hasCode(EVIDENCE_CODES)) kind = 'no_evidence'
  else if (
    hasCode(MODEL_CODES) ||
    textMatches(texts, /^unsupported model\.?$/i)
  ) {
    kind = 'unsupported_model'
  } else if (
    hasCode(FORMAT_CODES) ||
    textMatches(texts, /allowed extension/i) ||
    textMatches(texts, /^unsupported (?:file )?format\.?$/i) ||
    textMatches(texts, /^format must be /i)
  ) {
    kind = 'unsupported_format'
  } else if (
    input.status === 403 ||
    hasCode(PERMISSION_CODES) ||
    textMatches(texts, /^access denied\.?$/i) ||
    textMatches(texts, /^insufficient permissions\b/i)
  ) {
    kind = 'permission'
  }
  if (!kind) return null
  return { kind, ...ACTION_FAILURE_COPY[kind] }
}

/** Mapped failure when one matches; otherwise the existing detail formatter. */
export function mutationFailureNotice(
  status: number,
  data: unknown,
  fallback: string
): { title: string; message: string } {
  const mapped = presentActionFailure({ status, data })
  if (mapped) return { title: mapped.title, message: mapped.message }
  return {
    title: 'Could not complete that',
    message: formatApiErrorDetail(data, fallback),
  }
}
