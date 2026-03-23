'use client'

import { useRef, useState, useEffect } from 'react'
import { Button } from './Button'

export type RowAction =
  | { id: 'copy_id'; label: string; onClick: () => void }
  | { id: 'open'; label: string; href: string }
  | { id: 'edit_metadata'; label: string; onClick: () => void }
  | { id: 'delete'; label: string; onClick: () => void; variant?: 'danger' }
  | { id: 'restore'; label: string; onClick: () => void }

export function RegistryRowActionsMenu({
  actions,
  'aria-label': ariaLabel = 'Row actions',
}: {
  actions: RowAction[]
  'aria-label'?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div ref={ref} className="relative inline-block">
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setOpen((o) => !o)}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="true"
      >
        Actions ▾
      </Button>
      {open && (
        <ul
          role="menu"
          aria-label={ariaLabel}
          className="absolute right-0 top-full z-50 mt-1 min-w-[160px] rounded-xl border border-[var(--tc-border)] bg-[var(--tc-panel)] py-1 shadow-lg"
        >
          {actions.map((a) => (
            <li key={a.id} role="none">
              {a.id === 'open' && 'href' in a ? (
                <a
                  href={a.href}
                  role="menuitem"
                  className="block px-3 py-2 text-left text-sm text-[var(--tc-text)] hover:bg-white/10"
                  onClick={() => setOpen(false)}
                >
                  {a.label}
                </a>
              ) : (
                <button
                  type="button"
                  role="menuitem"
                  className={`block w-full px-3 py-2 text-left text-sm hover:bg-white/10 ${
                    a.id === 'delete' ? 'text-[var(--tc-danger)]' : 'text-[var(--tc-text)]'
                  }`}
                  onClick={() => {
                    if ('onClick' in a) a.onClick()
                    setOpen(false)
                  }}
                >
                  {a.label}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
