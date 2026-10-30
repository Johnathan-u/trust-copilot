'use client'

import { useEffect, useSyncExternalStore } from 'react'

import {
  ensureWorkspaceCreationPolicy,
  getWorkspaceCreationPhase,
  retryWorkspaceCreationPolicy,
  subscribeWorkspaceCreationPolicy,
  type WorkspaceCreationPhase,
} from '@/lib/workspace-creation-policy'

function serverPhase(): WorkspaceCreationPhase {
  return 'loading'
}

/**
 * Shared read of the creation policy.
 * The first paint stays on loading so a form is not shown before the read settles.
 */
export function useWorkspaceCreationPolicy() {
  const phase = useSyncExternalStore(
    subscribeWorkspaceCreationPolicy,
    getWorkspaceCreationPhase,
    serverPhase
  )

  useEffect(() => {
    ensureWorkspaceCreationPolicy()
  }, [])

  return { phase, retry: retryWorkspaceCreationPolicy }
}
