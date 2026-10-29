import { describe, expect, it } from 'vitest'
import {
  chooseReturnFocus,
  DIALOG_PLACEMENTS,
  DIALOG_ROLES,
  DRAWER_BACKDROP_STRIP,
  dialogAttributes,
  dialogContentClass,
  dialogPlacementClass,
  dialogRoleForDestructive,
  dialogSizeClass,
  nextTabbableIndex,
} from '@/lib/dialog'

describe('dialog primitive contract', () => {
  it('uses alertdialog only for destructive confirms', () => {
    expect(dialogRoleForDestructive(true)).toBe('alertdialog')
    expect(dialogRoleForDestructive(false)).toBe('dialog')
    expect(DIALOG_ROLES).toEqual(['dialog', 'alertdialog'])
  })

  it('wraps Tab and Shift+Tab at the ends of the focus cycle', () => {
    expect(nextTabbableIndex(0, 0, false)).toBe(0)
    expect(nextTabbableIndex(0, 1, false)).toBe(0)
    expect(nextTabbableIndex(0, 1, true)).toBe(0)
    expect(nextTabbableIndex(0, 3, false)).toBe(1)
    expect(nextTabbableIndex(1, 3, true)).toBe(0)
    expect(nextTabbableIndex(2, 3, false)).toBe(0)
    expect(nextTabbableIndex(0, 3, true)).toBe(2)
    expect(nextTabbableIndex(-1, 4, false)).toBe(0)
  })

  it('keeps start and end drawer placements on the shared dialog', () => {
    expect(DIALOG_PLACEMENTS).toEqual(['center', 'drawer-start', 'drawer-end'])
    expect(dialogPlacementClass['drawer-end'].root).toContain('justify-end')
    expect(dialogPlacementClass['drawer-start'].root).toContain('justify-start')
    expect(dialogPlacementClass.center.root).toContain('items-center')
    expect(dialogPlacementClass['drawer-end'].panel).not.toContain('max-w-md')
    expect(dialogSizeClass.lg).toBe('max-w-2xl')
    expect(dialogAttributes.initialDismiss).toBe('dismiss')
    expect(dialogAttributes.close).toBe('data-dialog-close')
    expect(dialogAttributes.backdrop).toBe('data-tc-dialog-backdrop')
  })

  it('leaves a backdrop strip beside a drawer and does not let the content wrapper fill it', () => {
    for (const placement of ['drawer-start', 'drawer-end'] as const) {
      const panel = dialogPlacementClass[placement].panel
      expect(panel).toContain(`calc(100%-${DRAWER_BACKDROP_STRIP})`)
      expect(panel).toContain('shrink-0')
      expect(panel).toContain('min-w-0')
      expect(panel).not.toContain('min(100%,20rem)')
    }
    expect(DRAWER_BACKDROP_STRIP).toBe('2.75rem')
    expect(dialogContentClass).toContain('min-w-0')
    expect(dialogContentClass).toContain('max-w-full')
    expect(dialogContentClass.split(/\s+/)).not.toContain('flex-1')
  })

  it('skips a hidden return target and uses the first visible focusable fallback', () => {
    const hiddenTrigger = { id: 'menu', visible: false, focusable: false }
    const main = { id: 'main-content', visible: true, focusable: true }
    const dockLink = { id: 'home', visible: true, focusable: true }
    expect(chooseReturnFocus([hiddenTrigger, main, dockLink])).toBe(main)
    expect(
      chooseReturnFocus([hiddenTrigger, { ...main, visible: false }, dockLink])
    ).toEqual(dockLink)
    expect(
      chooseReturnFocus([{ id: 'menu', visible: true, focusable: true }, main])
        ?.id
    ).toBe('menu')
    expect(
      chooseReturnFocus([{ id: 'none', visible: false, focusable: true }])
    ).toBeNull()
  })
})
