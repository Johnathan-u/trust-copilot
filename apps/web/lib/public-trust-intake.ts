/** Bounds shared by the public trust form and the intake API. */
export const PUBLIC_INTAKE_FIELD_MAX = 255
export const PUBLIC_INTAKE_MESSAGE_MAX = 10000

export type PublicIntakeAttempt = {
  slug: string
  email: string
  name: string
  subject: string
  message: string
  fileName: string
  fileSize: number
  fileLastModified: number
}

export function publicIntakeFingerprint(attempt: PublicIntakeAttempt): string {
  return JSON.stringify(attempt)
}

function safeDetail(data: unknown): string | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const detail = (data as { detail?: unknown }).detail
  if (typeof detail !== 'string') return null
  const text = detail.trim()
  if (!text || text.length > 300 || /[\r\n]/.test(text)) return null
  return text
}

export function publicIntakeClientError(input: {
  email: string
  name: string
  subject: string
  message: string
}): string | null {
  const email = input.email.trim()
  const name = input.name.trim()
  const subject = input.subject.trim()
  const message = input.message.trim()
  if (!email) return 'Enter an email address.'
  if (!message) return 'Enter a message.'
  if (
    email.length > PUBLIC_INTAKE_FIELD_MAX ||
    name.length > PUBLIC_INTAKE_FIELD_MAX ||
    subject.length > PUBLIC_INTAKE_FIELD_MAX ||
    message.length > PUBLIC_INTAKE_MESSAGE_MAX
  )
    return publicIntakeError(422, null)
  return null
}

/** Always a string. Validation lists and other non-strings are not rendered. */
export function publicIntakeError(status: number, data: unknown): string {
  if (status === 422)
    return 'Check the email, name, subject, and message. Name, subject, and email must be at most 255 characters, and the message must contain text and be at most 10,000 characters.'
  const detail = safeDetail(data)
  if (detail) return detail
  if (status === 409)
    return 'This submission was already started with different details. Restore the original details and submit again, or change them to send a separate request.'
  if (status === 413)
    return 'The file is too large. Choose a smaller file and try again.'
  if (status === 404)
    return 'This trust center could not be found. Check the link and try again.'
  return 'Submission could not be confirmed. Submit the same details again.'
}
