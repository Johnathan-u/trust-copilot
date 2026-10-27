'use client'

import { useEffect } from 'react'
import { Button } from './Button'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
}

export function Modal({ isOpen, onClose, title, children }: ModalProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    if (isOpen) {
      document.addEventListener('keydown', handler)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handler)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 backdrop-blur-sm"
        style={{ background: 'var(--tc-overlay)' }}
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 w-full max-w-md rounded-tc border border-tc-border p-tc-6 shadow-[var(--tc-shadow)] backdrop-blur-[20px]"
        style={{ background: 'var(--tc-panel)' }}
      >
        {title && (
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-tc-title font-semibold text-tc-text">
              {title}
            </h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              aria-label="Close"
            >
              ×
            </Button>
          </div>
        )}
        <div className="text-tc-text">{children}</div>
      </div>
    </div>
  )
}
