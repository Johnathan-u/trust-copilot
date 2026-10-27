import { describe, expect, it } from 'vitest'
import { disclosureTriggerProps } from './disclosure'

describe('disclosure popover trigger', () => {
  it('exposes aria-expanded and aria-controls for the panel', () => {
    expect(disclosureTriggerProps(true, 'sample-notifications')).toEqual({
      'aria-expanded': true,
      'aria-controls': 'sample-notifications',
    })
    expect(disclosureTriggerProps(false, 'sample-notifications')).toEqual({
      'aria-expanded': false,
      'aria-controls': 'sample-notifications',
    })
    expect(Object.keys(disclosureTriggerProps(true, 'sample-notifications'))).toEqual([
      'aria-expanded',
      'aria-controls',
    ])
  })
})
