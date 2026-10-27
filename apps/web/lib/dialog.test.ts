import { describe, expect, it } from 'vitest'
import {
  DIALOG_PLACEMENTS,
  DIALOG_ROLES,
  dialogAttributes,
  dialogPlacementClass,
  dialogRoleForDestructive,
  dialogSizeClass,
  nextTabbableIndex,
} from './dialog'

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

  it('keeps a drawer placement for a later navigation adopter', () => {
    expect(DIALOG_PLACEMENTS).toEqual(['center', 'drawer-start', 'drawer-end'])
    expect(dialogPlacementClass['drawer-end'].root).toContain('justify-end')
    expect(dialogPlacementClass['drawer-start'].root).toContain('justify-start')
    expect(dialogPlacementClass.center.root).toContain('items-center')
    expect(dialogPlacementClass['drawer-end'].panel).not.toContain('max-w-md')
    expect(dialogSizeClass.lg).toBe('max-w-2xl')
    expect(dialogAttributes.initialDismiss).toBe('dismiss')
    expect(dialogAttributes.close).toBe('data-dialog-close')
  })
})
