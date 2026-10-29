import { throwIfResponseNotOk } from '@/lib/api-error'

/** Delete one notification policy and refresh only after the API accepts it. */
export async function deleteNotificationPolicy(
  policyId: number,
  reload: () => void,
  fetchImpl: typeof fetch = fetch
): Promise<void> {
  const response = await fetchImpl(`/api/notifications/policies/${policyId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  await throwIfResponseNotOk(response)
  reload()
}
