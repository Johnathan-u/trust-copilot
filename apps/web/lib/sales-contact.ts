/**
 * Optional contact shown with an invitation.
 * An email becomes a mailto link. An https URL is used as itself.
 * Anything else, including an empty value, leaves the link hidden.
 */

const SALES_CONTACT_SUBJECT = 'Workspace access'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function parseSalesContact(
  raw: string | null | undefined
): string | null {
  const value = (raw ?? '').trim()
  if (!value) return null
  if (!/[\s/:]/.test(value) && EMAIL.test(value)) {
    return `mailto:${value}?subject=${encodeURIComponent(SALES_CONTACT_SUBJECT)}`
  }
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return null
  }
  if (url.protocol !== 'https:') return null
  return url.href
}

export function salesContactHref(
  raw: string | null | undefined = process.env.NEXT_PUBLIC_SALES_CONTACT
): string | null {
  return parseSalesContact(raw)
}
