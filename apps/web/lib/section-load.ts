import {
  ApiRequestError,
  presentHttpFailure,
  type ApiFailurePresentation,
} from './api-error'

export type SectionResult<T> =
  { ok: true; data: T } | { ok: false; failure: ApiFailurePresentation }

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (error instanceof Error && error.name === 'AbortError')
  )
}

export function failureOf(error: unknown): ApiFailurePresentation {
  if (error instanceof ApiRequestError) return error.failure
  if (isAbortError(error) || error instanceof TypeError) {
    return presentHttpFailure({ offline: true })
  }
  return presentHttpFailure({ malformed: true })
}

export async function readSectionJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    throw new ApiRequestError(presentHttpFailure({ status: response.status }))
  }
  const text = await response.text()
  if (!text.trim()) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    throw new ApiRequestError(presentHttpFailure({ malformed: true }))
  }
}

export function listFromPayload<T>(
  data: unknown,
  keys: readonly string[]
): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>
    for (const key of keys) {
      if (Array.isArray(record[key])) return record[key] as T[]
    }
  }
  throw new ApiRequestError(presentHttpFailure({ malformed: true }))
}

export function recordFromPayload(data: unknown): Record<string, unknown> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new ApiRequestError(presentHttpFailure({ malformed: true }))
  }
  return data as Record<string, unknown>
}

export function sectionFailure<T>(
  result: SectionResult<T>
): ApiFailurePresentation | null {
  if ('failure' in result) return result.failure
  return null
}

export async function loadSection<T>(
  request: Promise<Response>,
  parse: (data: unknown) => T
): Promise<SectionResult<T>> {
  try {
    const response = await request
    const data = await readSectionJson(response)
    return { ok: true, data: parse(data) }
  } catch (error) {
    if (isAbortError(error)) throw error
    return { ok: false, failure: failureOf(error) }
  }
}
