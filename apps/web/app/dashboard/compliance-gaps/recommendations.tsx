'use client'

import Link from 'next/link'
import { useCallback, useEffect, useId, useState, type ReactNode } from 'react'
import { Button, Card, ErrorState, LoadingState } from '@/components/ui'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { failureOf, readSectionJson } from '@/lib/section-load'
import {
  readRecommendationEvidence,
  readRecommendationQuestion,
  type Recommendation,
  type QuestionSource,
} from './recommendation-contract'

function useRecommendationSource<T>(
  url: string,
  workspaceId: number,
  parse: (value: unknown) => T
) {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{
    url: string
    workspaceId: number
    parse: (value: unknown) => T
    data: T | null
    failure: ApiFailurePresentation | null
  } | null>(null)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => {
      controller.abort()
      if (active)
        setResult({
          url,
          workspaceId,
          parse,
          data: null,
          failure: failureOf(
            new DOMException('Source request timed out', 'AbortError')
          ),
        })
    }, 15000)
    void fetch(url, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(readSectionJson)
      .then(parse)
      .then((data) => {
        if (active && !controller.signal.aborted)
          setResult({ url, workspaceId, parse, data, failure: null })
      })
      .catch((error: unknown) => {
        if (active)
          setResult({
            url,
            workspaceId,
            parse,
            data: null,
            failure: failureOf(error),
          })
      })
      .finally(() => clearTimeout(timeout))
    return () => {
      active = false
      clearTimeout(timeout)
      controller.abort()
    }
  }, [url, workspaceId, parse, attempt])
  const current =
    result?.url === url &&
    result.workspaceId === workspaceId &&
    result.parse === parse
      ? result
      : null
  return {
    data: current?.data ?? null,
    failure: current?.failure ?? null,
    retry: () => {
      setResult(null)
      setAttempt((value) => value + 1)
    },
  }
}

export function useRecommendationEvidence(id: number, workspaceId: number) {
  const parse = useCallback(
    (value: unknown) => readRecommendationEvidence(value, id, workspaceId),
    [id, workspaceId]
  )
  return useRecommendationSource(
    `/api/compliance/evidence/${id}`,
    workspaceId,
    parse
  )
}

export function useRecommendationQuestion(
  source: QuestionSource,
  workspaceId: number
) {
  const { question_id: questionId, questionnaire_id: questionnaireId } = source
  const parse = useCallback(
    (value: unknown) =>
      readRecommendationQuestion(
        value,
        { question_id: questionId, questionnaire_id: questionnaireId },
        workspaceId
      ),
    [questionId, questionnaireId, workspaceId]
  )
  return useRecommendationSource(
    `/api/questionnaires/${questionnaireId}?workspace_id=${workspaceId}`,
    workspaceId,
    parse
  )
}

const sourceLabels: Record<string, string> = {
  document: 'Document evidence',
  manual: 'Manual evidence',
  integration: 'Integration evidence',
  ai: 'AI evidence',
  slack: 'Slack evidence',
  gmail: 'Gmail evidence',
}

function EvidenceDetail({
  id,
  workspaceId,
}: {
  id: number
  workspaceId: number
}) {
  const result = useRecommendationEvidence(id, workspaceId)
  if (result.failure)
    return (
      <div className="space-y-2">
        <p className="font-medium text-tc-text">Evidence source unavailable.</p>
        <ErrorState failure={result.failure} onRetry={result.retry} />
      </div>
    )
  if (!result.data)
    return (
      <LoadingState label="Loading evidence source" onRetry={result.retry} />
    )
  return (
    <div className="space-y-2 text-tc-label">
      <p className="break-words font-semibold text-tc-text">
        {result.data.title || 'Untitled evidence'}
      </p>
      <p className="text-tc-muted">
        {Object.hasOwn(sourceLabels, result.data.source_type)
          ? sourceLabels[result.data.source_type]
          : 'Evidence item'}
      </p>
      <p className="text-tc-muted">
        A source reference does not establish approval, freshness or
        qualification.
      </p>
    </div>
  )
}

function SourceDisclosure({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  const contentId = useId()
  return (
    <div className="space-y-2">
      <Button
        variant="secondary"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? 'Hide' : 'View'} {label}
      </Button>
      <div id={contentId} hidden={!expanded}>
        {expanded ? children : null}
      </div>
    </div>
  )
}

const sourceLinkClass =
  'inline-flex min-h-11 items-center rounded text-tc-label text-tc-primary underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-tc-primary'

function QuestionDetail({
  source,
  workspaceId,
}: {
  source: QuestionSource
  workspaceId: number
}) {
  const result = useRecommendationQuestion(source, workspaceId)
  if (result.failure)
    return (
      <div className="space-y-2">
        <p className="font-medium text-tc-text">Question source unavailable.</p>
        <ErrorState failure={result.failure} onRetry={result.retry} />
      </div>
    )
  if (!result.data)
    return (
      <LoadingState label="Loading question source" onRetry={result.retry} />
    )
  return (
    <div className="space-y-2 text-tc-label">
      <p className="break-words font-semibold text-tc-text">
        {result.data.text}
      </p>
      {result.data.section ? (
        <p className="break-words text-tc-muted">
          Section: {result.data.section}
        </p>
      ) : null}
      <p className="break-words text-tc-muted">
        Questionnaire: {result.data.questionnaireTitle}
      </p>
      <Link
        prefetch={false}
        className={sourceLinkClass}
        href={`/dashboard/questionnaires/${result.data.questionnaireId}`}
      >
        Open source questionnaire
      </Link>
    </div>
  )
}

export function Recommendations({
  recommendations,
  workspaceId,
}: {
  recommendations: Recommendation[]
  workspaceId: number
}) {
  if (!recommendations.length) return null
  return (
    <section aria-labelledby="recommendations-heading">
      <Card className="space-y-3 p-5">
        <div>
          <h2
            id="recommendations-heading"
            className="text-sm font-semibold text-tc-text"
          >
            Recommended Next Evidence
          </h2>
          <p className="mt-1 text-xs text-tc-muted">
            Suggested documents to review against missing evidence. Source
            counts may differ from the reported suggestion count.
          </p>
        </div>
        <ul className="space-y-3">
          {recommendations.map((row, index) => (
            <li
              key={`${index}:${JSON.stringify(row)}`}
              className="min-w-0 space-y-3 rounded-lg border border-tc-border px-4 py-3"
            >
              <h3 className="break-words text-sm font-medium text-tc-text">
                {row.title || 'Untitled recommendation'}
              </h3>
              <p className="text-xs text-tc-muted">
                Reported suggestion count:{' '}
                <span className="font-semibold text-tc-text">
                  {row.improves_questions}
                </span>
              </p>
              {row.evidence_ids.map((id, sourceIndex) => (
                <SourceDisclosure
                  key={`${workspaceId}:${id}`}
                  label={`evidence source ${sourceIndex + 1}`}
                >
                  <EvidenceDetail id={id} workspaceId={workspaceId} />
                </SourceDisclosure>
              ))}
              {row.control_ids.length > 0 ? (
                <ul className="flex flex-wrap gap-x-4 gap-y-2">
                  {row.control_ids.map((id, sourceIndex) => (
                    <li key={id}>
                      <Link
                        prefetch={false}
                        className={sourceLinkClass}
                        href={`/dashboard/controls/${id}`}
                      >
                        View control source {sourceIndex + 1}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
              {row.question_sources.map((source, sourceIndex) => (
                <SourceDisclosure
                  key={`${workspaceId}:${source.question_id}:${source.questionnaire_id}`}
                  label={`question source ${sourceIndex + 1}`}
                >
                  <QuestionDetail source={source} workspaceId={workspaceId} />
                </SourceDisclosure>
              ))}
              {row.question_ids.length > row.question_sources.length ? (
                <p className="text-tc-caption text-tc-muted">
                  Question sources without detail:{' '}
                  {row.question_ids.length - row.question_sources.length}. Their
                  questionnaire links are unavailable.
                </p>
              ) : null}
              {!row.evidence_ids.length &&
              !row.control_ids.length &&
              !row.question_ids.length ? (
                <p className="text-tc-caption text-tc-muted">
                  Source detail is unavailable for this recommendation.
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </section>
  )
}
