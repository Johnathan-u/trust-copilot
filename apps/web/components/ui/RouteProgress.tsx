'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { usePathname } from 'next/navigation'

export function RouteProgress() {
  const pathname = usePathname()
  const [progress, setProgress] = useState(0)
  const [visible, setVisible] = useState(false)
  const prevPathname = useRef(pathname)
  const timerRef = useRef<ReturnType<typeof setTimeout>>()
  const frameRef = useRef<ReturnType<typeof setInterval>>()

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
    history.pushState = function (...args) {
      start()
      return orig(...args)
    }
    return () => {
      history.pushState = orig
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
