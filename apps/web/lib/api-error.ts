/** Normalize FastAPI / proxy error JSON for display. */

export function formatApiErrorDetail(data: unknown, fallback = 'Request failed'): string {
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
