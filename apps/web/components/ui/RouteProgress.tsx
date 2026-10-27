'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { usePathname } from 'next/navigation'

export function RouteProgress() {
  const pathname = usePathname()
  const [progress, setProgress] = useState(0)
  const [visible, setVisible] = useState(false)
  const prevPathname = useRef(pathname)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const frameRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  const start = useCallback(() => {
    clearTimeout(timerRef.current)
    clearInterval(frameRef.current)
    setProgress(15)
    setVisible(true)
    frameRef.current = setInterval(() => {
      setProgress((p) => {
        if (p >= 90) {
          clearInterval(frameRef.current)
          return 90
        }
        return p + (90 - p) * 0.08
      })
    }, 80)
  }, [])

  const finish = useCallback(() => {
    clearInterval(frameRef.current)
    setProgress(100)
    timerRef.current = setTimeout(() => {
      setVisible(false)
      setProgress(0)
    }, 300)
  }, [])

  useEffect(() => {
    if (pathname !== prevPathname.current) {
      finish()
      prevPathname.current = pathname
    }
  }, [pathname, finish])

  useEffect(() => {
    const orig = history.pushState.bind(history)
    let startTimer: ReturnType<typeof setTimeout> | undefined
    history.pushState = function (...args) {
      // Next's app router calls pushState from useInsertionEffect. setState
      // there is illegal in React 19, so start the bar on the next turn.
      clearTimeout(startTimer)
      startTimer = setTimeout(() => start(), 0)
      return orig(...args)
    }
    return () => {
      history.pushState = orig
      clearTimeout(startTimer)
      clearTimeout(timerRef.current)
      clearInterval(frameRef.current)
    }
  }, [start])

  if (!visible && progress === 0) return null

  return (
    <div
      className="fixed inset-x-0 top-0 z-[9999] h-[2px] pointer-events-none"
      style={{ opacity: visible ? 1 : 0, transition: 'opacity 200ms' }}
    >
      <div
        className="h-full bg-[var(--tc-primary)]"
        style={{
          width: `${progress}%`,
          transition: progress === 0 ? 'none' : 'width 200ms ease',
          boxShadow: '0 0 8px var(--tc-primary)',
        }}
      />
    </div>
  )
}
