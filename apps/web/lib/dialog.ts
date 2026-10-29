/**
 * Dialog behavior contract.
 *
 * The visual shell is `components/ui/Dialog`. The mobile navigation drawer
 * uses `placement: 'drawer-start'` and does not carry a second focus
 * implementation. This module has no DOM calls so unit tests can lock the
 * contract under the existing Node Vitest setup.
 */

export const DIALOG_ROLES = ['dialog', 'alertdialog'] as const
export type DialogRole = (typeof DIALOG_ROLES)[number]

export const DIALOG_PLACEMENTS = [
  'center',
  'drawer-start',
  'drawer-end',
] as const
export type DialogPlacement = (typeof DIALOG_PLACEMENTS)[number]

export const DIALOG_SIZES = ['sm', 'md', 'lg'] as const
export type DialogSize = (typeof DIALOG_SIZES)[number]

/** Stable attributes the shell and adopters share. */
export const dialogAttributes = {
  root: 'data-tc-dialog-root',
  backdrop: 'data-tc-dialog-backdrop',
  close: 'data-dialog-close',
  /** Present on the least-destructive control inside an alertdialog. */
  initial: 'data-dialog-initial',
  initialDismiss: 'dismiss',
} as const

/**
 * First candidate that is both visible and focusable. Hidden triggers, such
 * as the compact menu button after the viewport docks the sidebar, are
 * skipped so focus can move to a later fallback.
 */
export function chooseReturnFocus<
  T extends { visible: boolean; focusable: boolean },
>(candidates: readonly T[]): T | null {
  for (const candidate of candidates) {
    if (candidate.visible && candidate.focusable) return candidate
  }
  return null
}

/**
 * Width reserved beside a drawer so a 320px viewport still has a tap target
 * on the backdrop. The content wrapper stays `min-w-0 max-w-full` and does
 * not use `flex-1` on the row axis, so it cannot grow across that strip.
 */
export const DRAWER_BACKDROP_STRIP = '2.75rem'

export const dialogContentClass = 'min-h-0 min-w-0 max-w-full text-tc-text'

function drawerPanel(edge: 'border-r' | 'border-l'): string {
  const capped = `calc(100%-${DRAWER_BACKDROP_STRIP})`
  return [
    'relative z-10 flex h-full max-h-[100dvh]',
    `w-[min(20rem,${capped})] max-w-[${capped}]`,
    'min-w-0 shrink-0 flex-col overflow-y-auto overscroll-contain',
    edge,
    'border-tc-border p-tc-4 shadow-[var(--tc-shadow)]',
  ].join(' ')
}

export function dialogRoleForDestructive(destructive: boolean): DialogRole {
  return destructive ? 'alertdialog' : 'dialog'
}

/**
 * Next index in a tab cycle. `count` 0 returns 0 so callers can bail out
 * before focusing. A single stop stays put. Otherwise Tab wraps at the ends.
 */
export function nextTabbableIndex(
  current: number,
  count: number,
  shift: boolean
): number {
  if (count <= 0) return 0
  if (count === 1) return 0
  const index = Number.isFinite(current) ? current : -1
  if (shift) return index <= 0 ? count - 1 : index - 1
  return index >= count - 1 || index < 0 ? 0 : index + 1
}

const centerPanel =
  'relative z-10 flex max-h-[calc(100dvh-3rem)] w-full flex-col overflow-y-auto overscroll-contain rounded-tc border border-tc-border p-tc-6 shadow-[var(--tc-shadow)]'

/** Class fragments for each placement. Drawer widths are the side-panel shell. */
export const dialogPlacementClass: Record<
  DialogPlacement,
  { root: string; panel: string }
> = {
  center: {
    root: 'fixed inset-0 z-50 flex items-center justify-center p-tc-4',
    panel: centerPanel,
  },
  'drawer-start': {
    root: 'fixed inset-0 z-50 flex justify-start',
    panel: drawerPanel('border-r'),
  },
  'drawer-end': {
    root: 'fixed inset-0 z-50 flex justify-end',
    panel: drawerPanel('border-l'),
  },
}

export const dialogSizeClass: Record<DialogSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
}
