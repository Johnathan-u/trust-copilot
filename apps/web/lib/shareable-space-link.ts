export type SpaceLiveness = 'live' | 'inactive' | 'expired'

export function spaceLiveness(
  space: { is_active: boolean; expires_at: string | null },
  now: number
): SpaceLiveness {
  if (!space.is_active) return 'inactive'
  if (space.expires_at) {
    const expires = Date.parse(space.expires_at)
    if (!Number.isNaN(expires) && expires <= now) return 'expired'
  }
  return 'live'
}

/** Buyer URL for a token that exists only in memory. The token is not stored. */
export function buyerAccessLink(origin: string, token: string): string {
  const base = origin.replace(/\/$/, '')
  const params = new URLSearchParams({ token })
  return `${base}/share?${params.toString()}`
}
