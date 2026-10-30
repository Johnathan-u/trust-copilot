import type { RecommendedEvidence } from '@/lib/coverageConsumer'
import { recordFromPayload } from '@/lib/section-load'
import { positiveId } from './gap-contract'

export type QuestionSource = { question_id: number; questionnaire_id: number }
export type Recommendation = RecommendedEvidence & {
  question_sources: QuestionSource[]
}

function sourceIds(value: unknown): number[] {
  // Older snapshots did not include provenance. Absence is unavailable, not a
  // reason to infer identifiers from the title or suggestion count.
  if (value === undefined) return []
  if (
    !Array.isArray(value) ||
    value.some((id) => !positiveId(id)) ||
    new Set(value).size !== value.length
  )
    throw new Error('Invalid recommendation sources')
  return value as number[]
}

export function readRecommendations(value: unknown): Recommendation[] {
  if (!Array.isArray(value)) throw new Error('Missing recommendations')
  return value.map((item) => {
    const row = recordFromPayload(item)
    if (
      typeof row.title !== 'string' ||
      !Number.isSafeInteger(row.improves_questions) ||
      Number(row.improves_questions) < 0
    )
      throw new Error('Invalid recommendation')
    const questionIds = sourceIds(row.question_ids)
    const sources =
      row.question_sources === undefined ? [] : row.question_sources
    if (!Array.isArray(sources)) throw new Error('Invalid question sources')
    const seen = new Set<number>()
    const questionSources = sources.map((item) => {
      const source = recordFromPayload(item)
      if (
        !positiveId(source.question_id) ||
        !positiveId(source.questionnaire_id) ||
        !questionIds.includes(Number(source.question_id)) ||
        seen.has(Number(source.question_id))
      )
        throw new Error('Invalid question source')
      seen.add(Number(source.question_id))
      return {
        question_id: Number(source.question_id),
        questionnaire_id: Number(source.questionnaire_id),
      }
    })
    return {
      title: row.title,
      improves_questions: Number(row.improves_questions),
      evidence_ids: sourceIds(row.evidence_ids),
      control_ids: sourceIds(row.control_ids),
      question_ids: questionIds,
      question_sources: questionSources,
    }
  })
}

export type RecommendationQuestion = {
  questionId: number
  questionnaireId: number
  questionnaireTitle: string
  text: string
  section: string | null
}

export function readRecommendationQuestion(
  value: unknown,
  source: QuestionSource,
  workspaceId: number
): RecommendationQuestion {
  const row = recordFromPayload(value)
  if (
    row.id !== source.questionnaire_id ||
    (row.workspace_id !== undefined && row.workspace_id !== workspaceId) ||
    typeof row.filename !== 'string' ||
    !Array.isArray(row.questions)
  )
    throw new Error('Invalid questionnaire source')
  const matching = row.questions
    .map(recordFromPayload)
    .filter((question) => question.id === source.question_id)
  const question = matching[0]
  if (
    matching.length !== 1 ||
    typeof question.text !== 'string' ||
    (question.section !== null && typeof question.section !== 'string')
  )
    throw new Error('Question source unavailable')
  return {
    questionId: source.question_id,
    questionnaireId: source.questionnaire_id,
    questionnaireTitle: row.filename,
    text: question.text,
    section: typeof question.section === 'string' ? question.section : null,
  }
}

export type RecommendationEvidence = {
  id: number
  workspace_id: number
  title: string
  source_type: string
  document_id: number | null
  created_at: string | null
}

export function readRecommendationEvidence(
  value: unknown,
  evidenceId: number,
  workspaceId: number
): RecommendationEvidence {
  const row = recordFromPayload(value)
  if (
    row.id !== evidenceId ||
    row.workspace_id !== workspaceId ||
    typeof row.title !== 'string' ||
    typeof row.source_type !== 'string' ||
    (row.document_id !== null && !positiveId(row.document_id)) ||
    (row.created_at !== null &&
      (typeof row.created_at !== 'string' ||
        !Number.isFinite(Date.parse(row.created_at))))
  )
    throw new Error('Invalid evidence source')
  return row as RecommendationEvidence
}
