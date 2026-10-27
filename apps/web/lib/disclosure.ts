/**
 * Trigger contract for a non-modal disclosure popover.
 *
 * The panel is not a dialog: no role="dialog", no aria-modal, no focus trap,
 * and no inert background. `aria-controls` names the panel id. The panel may
 * be absent while the disclosure is collapsed.
 */

export function disclosureTriggerProps(open: boolean, panelId: string): {
  'aria-expanded': boolean
  'aria-controls': string
} {
  return {
    'aria-expanded': open,
    'aria-controls': panelId,
  }
}
