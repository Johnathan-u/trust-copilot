'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type CommandPaletteItem = {
  id: string
  label: string
  onSelect: () => void
}

export type CommandPaletteSection = {
  title: string
  items: CommandPaletteItem[]
}

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  sections: CommandPaletteSection[]
  query: string
  onQueryChange: (q: string) => void
  placeholder?: string
}

function flattenSections(sections: CommandPaletteSection[]): CommandPaletteItem[] {
  return sections.flatMap((s) => s.items)
}

export function CommandPalette({
  open,
  onClose,
  sections,
  query,
  onQueryChange,
  placeholder = 'Search or jump to action…',
}: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const flatItems = useMemo(() => flattenSections(sections), [sections])
  const itemCount = flatItems.length

  useEffect(() => {
    if (!open) return
    setSelectedIndex(0)
    inputRef.current?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prevOverflow
    }
  }, [open])

  useEffect(() => {
    setSelectedIndex((i) => (itemCount ? Math.min(i, itemCount - 1) : 0))
  }, [itemCount])

  useEffect(() => {
    const item = flatItems[selectedIndex]
    if (item) document.getElementById(`cmd-${item.id}`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex, flatItems])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex((i) => (i < itemCount - 1 ? i + 1 : 0))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex((i) => (i > 0 ? i - 1 : itemCount - 1))
        return
      }
      if (e.key === 'Enter' && itemCount > 0) {
        e.preventDefault()
        flatItems[selectedIndex]?.onSelect()
        onClose()
      }
    },
    [itemCount, selectedIndex, flatItems, onClose]
  )

  let cursor = 0
  const runSelected = useCallback(
    (item: CommandPaletteItem) => {
      item.onSelect()
      onClose()
    },
    [onClose]
  )

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        className="relative z-10 w-full max-w-xl rounded-2xl border border-[var(--tc-border)] shadow-[var(--tc-shadow)] overflow-hidden"
        style={{ background: 'var(--tc-panel)' }}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <div className="border-b border-[var(--tc-border)] px-4 py-3">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="w-full bg-transparent text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:outline-none text-sm"
            aria-autocomplete="list"
            aria-controls="command-palette-list"
            aria-activedescendant={flatItems[selectedIndex] ? `cmd-${flatItems[selectedIndex].id}` : undefined}
          />
        </div>
        <div
          ref={listRef}
          id="command-palette-list"
          role="listbox"
          className="max-h-[min(60vh,400px)] overflow-y-auto py-2"
        >
          {sections.map((section) => {
            if (section.items.length === 0) return null
            return (
              <div key={section.title} className="mb-2 last:mb-0">
                <div className="px-4 py-1.5 text-xs font-medium uppercase tracking-wider text-[var(--tc-muted)]">
                  {section.title}
                </div>
                {section.items.map((item) => {
                  const index = cursor++
                  const isSelected = index === selectedIndex
                  return (
                    <button
                      key={item.id}
                      id={`cmd-${item.id}`}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      className={`w-full px-4 py-2.5 text-left text-sm transition-colors ${
                        isSelected
                          ? 'bg-white/10 text-[var(--tc-text)]'
                          : 'text-[var(--tc-muted)] hover:bg-white/5 hover:text-[var(--tc-text)]'
                      }`}
                      onMouseEnter={() => setSelectedIndex(index)}
                      onClick={() => runSelected(item)}
                    >
                      {item.label}
                    </button>
                  )
                })}
              </div>
            )
          })}
          {flatItems.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-[var(--tc-muted)]">
              No results. Try a different search or jump to a page above.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
