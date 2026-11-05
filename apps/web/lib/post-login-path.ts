/**
 * Post-login redirect targets taken from `next` (or the same kind of parameter).
 *
 * The result is always a same-origin relative path. Absolute URLs, protocol-relative
 * URLs (`//host`), backslash tricks, control characters, `javascript:` and `data:`
 * schemes, and encoded forms of those are ignored. Callers then navigate to the
 * returned path; the fallback is `/dashboard`.
 */

export const DEFAULT_POST_LOGIN_PATH = '/dashboard'

/** Parser base only. It is not an allow-list: absolute URLs never start with `/`. */
const PARSER_BASE = 'https://post-login.invalid'
const MAX_DECODE_ROUNDS = 5

function hasForbiddenCharacter(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0
    // ASCII controls and whitespace, including the characters the URL parser strips.
    if (code <= 32 || code === 127) return true
    if (char === '\\') return true
  }
  return false
}

/** True when `value` can only navigate inside the current origin. */
function isSameOriginRelativePath(value: string): boolean {
  if (!value.startsWith('/') || value.startsWith('//')) return false
  if (hasForbiddenCharacter(value)) return false
  let url: URL
  try {
    url = new URL(value, PARSER_BASE)
  } catch {
    return false
  }
  return url.origin === PARSER_BASE && url.protocol === 'https:'
}

/**
 * Raw value plus each percent-decoding, so `%2F%2Fhost` and `%5C` cannot hide a
 * scheme, protocol-relative URL, or backslash. Malformed or still-nested encodings
 * fail closed.
 */
function decodedForms(value: string): string[] | null {
  const forms = [value]
  let current = value
  for (let round = 0; round < MAX_DECODE_ROUNDS; round += 1) {
    if (!current.includes('%')) return forms
    let decoded: string
    try {
      decoded = decodeURIComponent(current)
    } catch {
      return null
    }
    if (decoded === current) return forms
    forms.push(decoded)
    current = decoded
  }
  if (!current.includes('%')) return forms
  try {
    if (decodeURIComponent(current) !== current) return null
  } catch {
    return null
  }
  return forms
}

export function safePostLoginPath(value: string | null | undefined): string {
  if (typeof value !== 'string' || value.length === 0) {
    return DEFAULT_POST_LOGIN_PATH
  }
  const forms = decodedForms(value)
  if (!forms || forms.some((form) => !isSameOriginRelativePath(form))) {
    return DEFAULT_POST_LOGIN_PATH
  }
  return value
}
