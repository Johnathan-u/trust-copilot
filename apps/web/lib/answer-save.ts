import type { RowSavePhase } from '@/lib/action-copy'

export interface AnswerSaveRequest {
  url: string
  method: 'POST' | 'PATCH'
  body: Record<string, unknown>
}

/**
 * An existing answer is a PATCH and includes the updated_at the editor loaded.
 * A question with no answer id is a create and has no revision yet.
 */
export function answerSaveRequest(input: {
  questionId: number
  text: string
  answerId?: number
  status?: string
  updatedAt?: string | null
}): AnswerSaveRequest {
  if (input.answerId) {
    const body: Record<string, unknown> = {
      text: input.text,
      updated_at: input.updatedAt ?? null,
    }
    if (input.status) body.status = input.status
    return {
      url: `/api/answers/${input.answerId}`,
      method: 'PATCH',
      body,
    }
  }
  return {
    url: '/api/answers',
    method: 'POST',
    body: {
      question_id: input.questionId,
      text: input.text,
      status: input.status || 'draft',
    },
  }
}

export type AnswerSaveOutcome =
  | {
      saved: true
      text: string
      phase: Extract<RowSavePhase, 'saved' | 'approved'>
    }
  | { saved: false; text: string; phase: undefined }

/**
 * 403, 409, and 500 are not a save. The typed text stays, and the phase stays
 * unset so the row label remains "Not saved yet".
 */
export function answerRowAfterSave(input: {
  httpStatus: number
  typedText: string
  approving: boolean
}): AnswerSaveOutcome {
  if (input.httpStatus >= 200 && input.httpStatus < 300) {
    return {
      saved: true,
      text: input.typedText,
      phase: input.approving ? 'approved' : 'saved',
    }
  }
  return {
    saved: false,
    text: input.typedText,
    phase: undefined,
  }
}
