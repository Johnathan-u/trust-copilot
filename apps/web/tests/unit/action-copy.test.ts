import { describe, expect, it } from 'vitest'

import {
  ACTION_SUCCESS_DETAIL,
  ACTION_VERBS,
  CONFIRMED_ACTIONS,
  actionVerb,
  confirmedActionNotice,
  rowSaveLabel,
} from '@/lib/action-copy'

describe('confirmed action verbs', () => {
  it('uses one idle, pending, and success form for each action', () => {
    expect(CONFIRMED_ACTIONS).toEqual([
      'save',
      'upload',
      'generate',
      'export',
      'approve',
    ])
    for (const action of CONFIRMED_ACTIONS) {
      const verbs = ACTION_VERBS[action]
      expect(verbs.pending).not.toBe(verbs.success)
      expect(verbs.idle).not.toBe(verbs.success)
      expect(verbs.pending.toLowerCase()).not.toContain('done')
      expect(verbs.pending).not.toBe(verbs.idle)
      expect(actionVerb(action, 'pending')).toBe(verbs.pending)
      expect(actionVerb(action, 'success')).toBe(verbs.success)
    }
  })

  it('keeps success copy for a confirmed result only', () => {
    const saved = confirmedActionNotice('save')
    expect(saved).toEqual({
      title: 'Saved',
      message: ACTION_SUCCESS_DETAIL.save,
    })
    expect(confirmedActionNotice('upload').title).toBe('Uploaded')
    expect(confirmedActionNotice('generate').title).toBe('Generated')
    expect(confirmedActionNotice('export').title).toBe('Exported')
    expect(confirmedActionNotice('approve').title).toBe('Approved')
    expect(saved.message.toLowerCase()).not.toContain('evidence-backed')
  })

  it('does not call an unconfirmed answer saved', () => {
    expect(rowSaveLabel(undefined)).toBe('Not saved yet')
    expect(rowSaveLabel('saving')).toBe('Saving')
    expect(rowSaveLabel('saved')).toBe('Saved')
    expect(rowSaveLabel('approving')).toBe('Approving')
    expect(rowSaveLabel('approved')).toBe('Approved')
  })
})
