import { describe, expect, it } from 'vitest'
import { retainedQuestionLabel } from '@/app/dashboard/questionnaires/[id]/page'

describe('retained question on the review page', () => {
  it('labels a dropped question and keeps its approved answer', () => {
    expect(
      retainedQuestionLabel({
        source_location: 'not_in_current_file',
        answer: { status: 'approved', text: 'Approved answer stays' },
      })
    ).toBe('Not in the current file. Approved answer: Approved answer stays')
  })
  it('does not label a question that is still in the file', () => {
    expect(
      retainedQuestionLabel({
        source_location: '{"sheet":"Sheet","row":2,"col":1}',
        answer: { status: 'approved', text: 'Approved answer stays' },
      })
    ).toBeNull()
  })
})
