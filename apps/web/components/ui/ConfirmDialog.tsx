'use client'

import { useCallback, useState } from 'react'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { Toast } from './Toast'
import { dialogAttributes } from '@/lib/dialog'
import {
  DESTRUCTIVE_CONFIRM_ERROR_TITLE,
  destructiveConfirmErrorToast,
  nextDestructiveConfirmState,
} from '@/lib/destructive-confirm'

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
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      role="alertdialog"
      closeDisabled={busy}
    >
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
        <Button
          type="button"
          variant="danger"
          size="sm"
          onClick={onConfirm}
          disabled={busy}
        >
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
  const [busy, setBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const confirm = useCallback((next: DestructiveConfirmRequest) => {
    setErrorMessage(null)
    setRequest(next)
  }, [])
  const close = useCallback(() => {
    if (busy) return
    setRequest(null)
  }, [busy])
  const run = useCallback(() => {
    const current = request
    if (!current || busy) return
    setBusy(true)
    void (async () => {
      let outcome: 'fulfilled' | 'rejected' = 'fulfilled'
      let message: string | null = null
      try {
        await current.onConfirm()
      } catch (reason) {
        outcome = 'rejected'
        message = destructiveConfirmErrorToast(reason).message
      }
      const next = nextDestructiveConfirmState(outcome)
      setBusy(next.busy)
      if (!next.open) setRequest(null)
      if (next.announceError && message) setErrorMessage(message)
    })()
  }, [request, busy])

  const dialog = (
    <>
      <ConfirmDialog
        open={request != null}
        title={request?.title ?? 'Confirm'}
        description={request?.description ?? ''}
        confirmLabel={request?.confirmLabel ?? 'Confirm'}
        onClose={close}
        onConfirm={run}
        busy={busy}
      />
      {errorMessage ? (
        <Toast
          title={DESTRUCTIVE_CONFIRM_ERROR_TITLE}
          message={errorMessage}
          type="error"
          onDismiss={() => setErrorMessage(null)}
        />
      ) : null}
    </>
  )

  return { confirm, dialog }
}
