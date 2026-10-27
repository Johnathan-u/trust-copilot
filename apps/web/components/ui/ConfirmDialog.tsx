'use client'

import { useCallback, useState } from 'react'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { dialogAttributes } from '@/lib/dialog'

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onClose,
  onConfirm,
  busy = false,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  onClose: () => void
  onConfirm: () => void
  busy?: boolean
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title} description={description} role="alertdialog" closeDisabled={busy}>
      <div className="flex justify-end gap-tc-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClose}
          disabled={busy}
          {...{ [dialogAttributes.initial]: dialogAttributes.initialDismiss }}
        >
          Cancel
        </Button>
        <Button type="button" variant="danger" size="sm" onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </Dialog>
  )
}

export type DestructiveConfirmRequest = {
  title: string
  description: string
  confirmLabel: string
  onConfirm: () => void | Promise<void>
}

/** Replaces `window.confirm` for destructive actions. The dialog is an alertdialog. */
export function useDestructiveConfirm() {
  const [request, setRequest] = useState<DestructiveConfirmRequest | null>(null)
  const confirm = useCallback((next: DestructiveConfirmRequest) => {
    setRequest(next)
  }, [])
  const close = useCallback(() => setRequest(null), [])
  const run = useCallback(() => {
    const current = request
    setRequest(null)
    if (current) void current.onConfirm()
  }, [request])

  const dialog = (
    <ConfirmDialog
      open={request != null}
      title={request?.title ?? 'Confirm'}
      description={request?.description ?? ''}
      confirmLabel={request?.confirmLabel ?? 'Confirm'}
      onClose={close}
      onConfirm={run}
    />
  )

  return { confirm, dialog }
}
