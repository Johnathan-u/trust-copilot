/**
 * Read whether the signed-in person may create a workspace.
 * The response is one boolean. Anything else, including a failed read,
 * stays off the screen and out of logs.
 */

export const WORKSPACE_CREATION_POLICY_PATH = '/api/workspaces/creation-policy'

export const WORKSPACE_CREATION_UNAVAILABLE_MESSAGE =
  'Workspace creation could not be checked. Try again.'

export type WorkspaceCreationPhase =
  'loading' | 'allowed' | 'denied' | 'unavailable'

export type SettledWorkspaceCreationPhase = Exclude<
  WorkspaceCreationPhase,
  'loading'
>

type Listener = () => void

let phase: WorkspaceCreationPhase = 'loading'
let started = false
let requestGeneration = 0
const listeners = new Set<Listener>()

function isExactPolicy(
  body: unknown
): body is { can_create_workspace: boolean } {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return false
  }
  const record = body as Record<string, unknown>
  const keys = Object.keys(record)
  return (
    keys.length === 1 &&
    keys[0] === 'can_create_workspace' &&
    typeof record.can_create_workspace === 'boolean'
  )
}

/** Map a policy response to a phase. The body is not retained. */
export function parseWorkspaceCreationPolicy(
  status: number,
  body: unknown
): SettledWorkspaceCreationPhase {
  if (status !== 200 || !isExactPolicy(body)) return 'unavailable'
  return body.can_create_workspace ? 'allowed' : 'denied'
}

export async function readWorkspaceCreationPolicy(
  fetchImpl: typeof fetch = globalThis.fetch,
  signal?: AbortSignal
): Promise<SettledWorkspaceCreationPhase> {
  try {
    const response = await fetchImpl(WORKSPACE_CREATION_POLICY_PATH, {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json' },
      signal,
    })
    const body = await response.json().catch(() => null)
    return parseWorkspaceCreationPolicy(response.status, body)
  } catch {
    return 'unavailable'
  }
}

function emit(next: WorkspaceCreationPhase) {
  phase = next
  for (const listener of listeners) listener()
}

function settle(generation: number, next: SettledWorkspaceCreationPhase) {
  if (generation !== requestGeneration) return
  emit(next)
}

export function getWorkspaceCreationPhase(): WorkspaceCreationPhase {
  return phase
}

export function subscribeWorkspaceCreationPolicy(listener: Listener) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function ensureWorkspaceCreationPolicy() {
  if (started) return
  started = true
  const generation = ++requestGeneration
  void readWorkspaceCreationPolicy().then((next) => settle(generation, next))
}

export function retryWorkspaceCreationPolicy() {
  started = true
  const generation = ++requestGeneration
  emit('loading')
  void readWorkspaceCreationPolicy().then((next) => settle(generation, next))
}

/** Test-only. Drops listeners and ignores a read that is still in flight. */
export function resetWorkspaceCreationPolicyForTests() {
  phase = 'loading'
  started = false
  requestGeneration += 1
  listeners.clear()
}
