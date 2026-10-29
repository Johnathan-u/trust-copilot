'use client'

import type { RefObject } from 'react'
import { Dialog } from '@/components/ui/Dialog'
import { Sidebar } from './Sidebar'

interface NavDrawerProps {
  open: boolean
  onClose: () => void
  returnFocusRef?: RefObject<HTMLElement | null>
}

/**
 * Mobile navigation. Focus trap, Escape, inert background, and focus return
 * come from the shared dialog primitive. The panel stays on the start edge.
 */
export function NavDrawer({ open, onClose, returnFocusRef }: NavDrawerProps) {
  return (
    <div className="md:hidden">
      <Dialog
        open={open}
        onClose={onClose}
        title="Navigation"
        placement="drawer-start"
        id="app-navigation"
        returnFocusRef={returnFocusRef}
      >
        <Sidebar onNavigate={onClose} className="min-h-0 flex-1 border-r-0" />
      </Dialog>
    </div>
  )
}
