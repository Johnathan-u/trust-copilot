'use client'

import type { ReactNode, RefObject } from 'react'
import { Dialog } from './Dialog'
import type { DialogRole, DialogSize } from '@/lib/dialog'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: string
  description?: string
  children: ReactNode
  role?: DialogRole
  size?: DialogSize
  closeDisabled?: boolean
  initialFocusRef?: RefObject<HTMLElement | null>
  panelClassName?: string
}

/** Existing call-site name for the shared dialog. New code can use `Dialog` directly. */
export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  role = 'dialog',
  size = 'md',
  closeDisabled = false,
  initialFocusRef,
  panelClassName,
}: ModalProps) {
  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      title={title && title.trim() ? title : 'Dialog'}
      description={description}
      role={role}
      size={size}
      closeDisabled={closeDisabled}
      initialFocusRef={initialFocusRef}
      panelClassName={panelClassName}
    >
      {children}
    </Dialog>
  )
}
