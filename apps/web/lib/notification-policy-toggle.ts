import { throwIfResponseNotOk } from '@/lib/api-error'

export function notificationPolicyErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return 'Request failed'
}

/** Toggle one policy. The promise always settles, and the list reloads either way. */
export async function toggleNotificationPolicy(
  policy: { id: number; enabled: boolean },
  report: {
    reload: () => void
    setError: (message: string | null) => void
  },
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  try {
    const response = await fetchImpl(
      `/api/notifications/policies/${policy.id}`,
      {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !policy.enabled }),
      }
    )
    await throwIfResponseNotOk(response)
    report.setError(null)
  } catch (error) {
    report.setError(notificationPolicyErrorMessage(error))
  } finally {
    report.reload()
  }
}
