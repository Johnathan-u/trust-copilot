'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { failureOf, isAbortError } from '@/lib/section-load'
import { listPhase, type SectionPhase } from '@/lib/ui-state'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'

export function useSectionQuery<T>(options: {
  enabled?: boolean
  load: (signal: AbortSignal) => Promise<T[]>
  deps?: readonly unknown[]
}) {
  const enabled = options.enabled !== false
  const depsKey = JSON.stringify(options.deps ?? [])
  const loadRef = useRef(options.load)
  useEffect(() => {
    loadRef.current = options.load
  }, [options.load])

  const [phase, setPhase] = useState<SectionPhase>('loading')
  const [items, setItems] = useState<T[]>([])
  const [failure, setFailure] = useState<ApiFailurePresentation | null>(null)
  const [loadId, setLoadId] = useState(0)
  const [reloadToken, setReloadToken] = useState(0)
  const requestKey = `${enabled ? '1' : '0'}\n${depsKey}\n${reloadToken}`
  const generation = useKeyedGeneration(requestKey)
  if (generation.changed && enabled) {
    setPhase('loading')
    setFailure(null)
    setLoadId(generation.generation)
  }

  const reload = useCallback(() => {
    setReloadToken((value) => value + 1)
  }, [])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let active = true
    loadRef
      .current(controller.signal)
      .then((next) => {
        if (!active) return
        setItems(next)
        setFailure(null)
        setPhase(listPhase(next.length))
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return
        setItems([])
        setFailure(failureOf(error))
        setPhase('error')
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [enabled, reloadToken, depsKey])

  return { phase, items, failure, reload, loadId }
}
