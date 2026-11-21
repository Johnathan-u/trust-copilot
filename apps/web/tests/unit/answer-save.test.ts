import { describe, expect, it } from 'vitest'

import { rowSaveLabel } from '@/lib/action-copy'
import { answerRowAfterSave, answerSaveRequest } from '@/lib/answer-save'

const typed = 'Synthetic draft the editor typed.'
const loadedRevision = '2026-11-21T10:00:00'

describe('answer row save', () => {
  it('sends the revision the editor loaded', () => {
    const request = answerSaveRequest({
      questionId: 3,
      text: typed,
      answerId: 11,
      updatedAt: loadedRevision,
    })
    expect(request.method).toBe('PATCH')
    expect(request.url).toBe('/api/answers/11')
    expect(request.body).toEqual({
      text: typed,
      updated_at: loadedRevision,
    })
  })

  it.each([403, 409, 500])(
    'keeps the typed text and Not saved yet on HTTP %s',
    (status) => {
      const row = answerRowAfterSave({
        httpStatus: status,
        typedText: typed,
        approving: false,
      })
      expect(row.saved).toBe(false)
      expect(row.text).toBe(typed)
      expect(row.phase).toBeUndefined()
      expect(rowSaveLabel(row.phase)).toBe('Not saved yet')
    }
  )
})
