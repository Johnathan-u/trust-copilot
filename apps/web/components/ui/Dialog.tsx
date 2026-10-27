'use client'

import { useId, useRef, type ReactNode, type RefObject } from 'react'
import { Button } from './Button'
import { useDialogBehavior } from './useDialogBehavior'
import {
  dialogAttributes,
  dialogPlacementClass,
  dialogSizeClass,
  type DialogPlacement,
  type DialogRole,
  type DialogSize,
} from '@/lib/dialog'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  role?: DialogRole
  placement?: DialogPlacement
  size?: DialogSize
  children?: ReactNode
  initialFocusRef?: RefObject<HTMLElement | null>
  returnFocusRef?: RefObject<HTMLElement | null>
  closeDisabled?: boolean
  hideClose?: boolean
  panelClassName?: string
}

/**
 * Shared modal shell. Focus moves inside on open, Tab cycles inside the dialog,
 * Escape closes it, and focus returns to the trigger. The rest of the page is
 * inert. `placement="drawer-end"` or `"drawer-start"` is the same behavior for
 * a later navigation drawer (TC-14-006); this ticket does not mount that drawer.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  role = 'dialog',
  placement = 'center',
  size = 'md',
  children,
  initialFocusRef,
  returnFocusRef,
  closeDisabled = false,
  hideClose = false,
  panelClassName = '',
}: DialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const boundaryRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const placementClass = dialogPlacementClass[placement]
  const described = Boolean(description && description.trim())

  useDialogBehavior({
    open,
    onClose,
    dialogRef,
    boundaryRef,
    initialFocusRef,
    returnFocusRef,
    role,
    closeOnEscape: !closeDisabled,
    lockScroll: true,
  })

  if (!open) return null

  const close = () => {
    if (!closeDisabled) onClose()
  }

  return (
    <div
      ref={boundaryRef}
      className={placementClass.root}
      {...{ [dialogAttributes.root]: '' }}
    >
      <div
        className="absolute inset-0 backdrop-blur-sm"
        style={{ background: 'var(--tc-overlay)' }}
        onClick={close}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={described ? descriptionId : undefined}
        tabIndex={-1}
        className={`${placementClass.panel} ${placement === 'center' ? dialogSizeClass[size] : ''} ${panelClassName}`}
        style={{ background: 'var(--tc-surface-overlay)' }}
      >
        <div className="mb-tc-4 flex items-start justify-between gap-tc-3">
          <h2 id={titleId} className="text-tc-title font-semibold text-tc-text">
            {title}
          </h2>
          {hideClose ? null : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={close}
              disabled={closeDisabled}
              aria-label="Close"
              {...{ [dialogAttributes.close]: '' }}
            >
              ×
            </Button>
          )}
        </div>
        {described ? (
          <p id={descriptionId} className="mb-tc-4 text-tc-label text-tc-muted">
            {description}
          </p>
        ) : null}
        <div className="text-tc-text">{children}</div>
      </div>
    </div>
  )
}
