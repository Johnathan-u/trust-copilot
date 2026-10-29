'use client'

import { useState } from 'react'
import { nextGeneration } from '@/lib/render-state'

/**
 * Store the previous key in state during render. `changed` is true for the
 * render that observes a new key. Generation is an absolute count, so a
 * repeated render of the same previous key computes the same next value.
 */
export function useKeyedGeneration(
  key: string,
  options?: { runOnMount?: boolean }
): { changed: boolean; generation: number } {
  const runOnMount = options?.runOnMount !== false
  const [snapshot, setSnapshot] = useState<{
    key: string | null
    generation: number
  }>({
    key: runOnMount ? null : key,
    generation: 0,
  })
  if (snapshot.key !== key) {
    const next = nextGeneration(snapshot.key, key, snapshot.generation)
    setSnapshot({ key: next.key, generation: next.generation })
    return { changed: true, generation: next.generation }
  }
  return { changed: false, generation: snapshot.generation }
}
