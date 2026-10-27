'use client'

import { useRef, useState } from 'react'
import { DeleteConfirmationModal, Dialog, ToastNotice } from '@/components/ui'
import { autoDismissMs, type ToastSeverity } from '@/lib/toast'
import type { ThemeName } from '@/lib/design-tokens'

type Notice = {
  title: string
  message: string
  type: ToastSeverity
}

export function DialogShowcase({ theme }: { theme: ThemeName }) {
  const [renameOpen, setRenameOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [notes, setNotes] = useState('')
  const [notice, setNotice] = useState<Notice | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }

  const showNotice = (next: Notice, hold: boolean) => {
    clearTimer()
    setNotice(next)
    if (hold) return
    const ms = autoDismissMs(next.type)
    if (ms == null) return
    timer.current = setTimeout(() => {
      timer.current = null
      setNotice(null)
    }, ms)
  }

  const onNotes = (value: string) => {
    setNotes(value)
    if (value.endsWith(' ok')) {
      showNotice({ title: 'Saved', message: 'Synthetic status saved.', type: 'success' }, false)
    } else if (value.endsWith(' err')) {
      showNotice({ title: 'Save failed', message: 'Synthetic error stayed on screen.', type: 'error' }, false)
    }
  }

  return (
    <main
      id="dialog-showcase"
      data-testid="dialog-showcase"
      data-expected-theme={theme}
      className="relative z-[1] min-h-screen text-tc-text"
      style={{ background: 'var(--tc-body-background)' }}
    >
      <div className="mx-auto flex max-w-3xl flex-col gap-tc-6 px-tc-4 py-tc-6">
        <header className="flex flex-col gap-tc-3">
          <p className="text-tc-caption font-semibold uppercase tracking-wider text-tc-muted">Trust Copilot</p>
          <h1 className="text-tc-headline font-bold">Dialogs and notifications</h1>
          <p className="max-w-2xl text-tc-body text-tc-muted">
            Synthetic sample for focus trap, destructive confirmation and live announcements. No customer data is shown.
          </p>
        </header>

        <div className="flex flex-col gap-tc-2">
          <label htmlFor="working-notes" className="text-tc-label font-medium text-tc-text">
            Working notes
          </label>
          <input
            id="working-notes"
            value={notes}
            onChange={(event) => onNotes(event.target.value)}
            className="w-full rounded-tc-sm border border-tc-border-strong bg-tc-surface-overlay px-tc-3 py-tc-2 text-tc-body text-tc-text"
            autoComplete="off"
          />
        </div>

        <div className="flex flex-wrap gap-tc-2">
          <button
            type="button"
            className="inline-flex min-h-tc-8 items-center rounded-tc-sm bg-tc-primary-solid px-tc-4 text-tc-label font-semibold text-tc-on-primary"
            onClick={() => setRenameOpen(true)}
          >
            Rename sample
          </button>
          <button
            type="button"
            className="inline-flex min-h-tc-8 items-center rounded-tc-sm bg-[var(--tc-danger-solid)] px-tc-4 text-tc-label font-semibold text-[var(--tc-on-danger)]"
            onClick={() => setConfirmOpen(true)}
          >
            Delete sample record
          </button>
          <button
            type="button"
            className="inline-flex min-h-tc-8 items-center rounded-tc-sm border border-tc-border-strong px-tc-4 text-tc-label font-semibold text-tc-text"
            onClick={() => setDrawerOpen(true)}
          >
            Open side panel
          </button>
          <button
            type="button"
            className="inline-flex min-h-tc-8 items-center rounded-tc-sm border border-tc-border-strong px-tc-4 text-tc-label font-semibold text-tc-text"
            onClick={() => showNotice({ title: 'Saved', message: 'Synthetic status saved.', type: 'success' }, true)}
          >
            Show status
          </button>
          <button
            type="button"
            className="inline-flex min-h-tc-8 items-center rounded-tc-sm border border-tc-border-strong px-tc-4 text-tc-label font-semibold text-tc-text"
            onClick={() =>
              showNotice({ title: 'Save failed', message: 'Synthetic error stayed on screen.', type: 'error' }, true)
            }
          >
            Show error
          </button>
        </div>
      </div>

      <Dialog
        open={renameOpen}
        onClose={() => setRenameOpen(false)}
        title="Rename sample record"
        description="Choose a new name for the synthetic sample record."
      >
        <form
          className="flex flex-col gap-tc-3"
          onSubmit={(event) => {
            event.preventDefault()
            setRenameOpen(false)
          }}
        >
          <div className="flex flex-col gap-tc-1">
            <label htmlFor="sample-name" className="text-tc-label font-medium">
              Record name
            </label>
            <input
              id="sample-name"
              defaultValue="Sample record"
              className="w-full rounded-tc-sm border border-tc-border-strong bg-tc-surface-overlay px-tc-3 py-tc-2 text-tc-body text-tc-text"
            />
          </div>
          <a href="#dialog-showcase" className="text-tc-label text-tc-primary">
            Field help
          </a>
          <div className="flex justify-end gap-tc-2">
            <button type="button" className="min-h-tc-6 px-tc-3 text-tc-label" onClick={() => setRenameOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="min-h-tc-6 rounded-tc-sm bg-tc-primary-solid px-tc-3 text-tc-label font-semibold text-tc-on-primary">
              Save name
            </button>
          </div>
        </form>
      </Dialog>

      <DeleteConfirmationModal
        isOpen={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => setConfirmOpen(false)}
        title="Delete sample record?"
        recordLabel="Sample evidence record"
        displayId="DOC-SYN-14"
        dependencies={{ questionnaires: 2 }}
        unmodeledWarning="Linked exports stay listed until the next refresh."
      />

      <Dialog
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        placement="drawer-end"
        title="Navigation"
        description="Synthetic side panel. A later navigation drawer can adopt this placement."
      >
        <nav className="flex flex-col gap-tc-3" aria-label="Sample destinations">
          <a href="#dialog-showcase" className="text-tc-label text-tc-primary">
            Documents
          </a>
          <a href="#dialog-showcase" className="text-tc-label text-tc-primary">
            Questionnaires
          </a>
        </nav>
      </Dialog>

      {notice ? (
        <ToastNotice
          title={notice.title}
          message={notice.message}
          type={notice.type}
          onDismiss={() => {
            clearTimer()
            setNotice(null)
          }}
        />
      ) : null}
    </main>
  )
}
