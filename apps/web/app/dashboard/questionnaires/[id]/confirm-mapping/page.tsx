'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { Button, Card, ErrorState, LoadingState } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  mutationFailureNotice,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import { failureOf, isAbortError, readSectionJson } from '@/lib/section-load'

type Item = {
  id: number
  question_text: string
  status: string
  preferred_control_id: number | null
  preferred_framework_key: string | null
}

type Payload = {
  questionnaire_id: number
  display_id: string
  filename: string
  mapping_ambiguous: boolean
  needs_review: boolean
  items: Item[]
}

function isPayload(value: unknown): value is Payload {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as { items?: unknown; filename?: unknown }
  return typeof record.filename === 'string' && Array.isArray(record.items)
}

export default function ConfirmMappingPage() {
  const params = useParams()
  const questionnaireId = Number(params.id)
  const { workspace, permissions, loading: authLoading } = useAuth()
  const workspaceId = workspace?.id
  const canEdit = permissions.can_edit
  const [attempt, setAttempt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [failure, setFailure] = useState<ApiFailurePresentation | null>(null)
  const [payload, setPayload] = useState<Payload | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const invalidId = !Number.isInteger(questionnaireId) || questionnaireId <= 0

  useEffect(() => {
    if (authLoading || workspaceId == null || invalidId) return
    const controller = new AbortController()
    void (async () => {
      await Promise.resolve()
      if (controller.signal.aborted) return
      setLoading(true)
      try {
        const response = await fetch(
          `/api/questionnaires/${questionnaireId}/mapping-confirmation?workspace_id=${workspaceId}`,
          {
            credentials: 'include',
            signal: controller.signal,
            cache: 'no-store',
          }
        )
        const data = await readSectionJson(response)
        if (controller.signal.aborted) return
        if (!isPayload(data)) throw new Error('malformed mapping confirmation')
        setPayload(data)
        setSelected(data.items.map((item) => item.id))
        setFailure(null)
      } catch (error) {
        if (controller.signal.aborted || isAbortError(error)) return
        setPayload(null)
        setFailure(failureOf(error))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [authLoading, workspaceId, questionnaireId, attempt, invalidId])

  const confirm = () => {
    if (!canEdit || workspaceId == null || selected.length === 0 || busy) return
    setBusy(true)
    setNotice(null)
    setActionError(null)
    void fetch(
      `/api/questionnaires/${questionnaireId}/mapping-confirmation?workspace_id=${workspaceId}`,
      {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mapping_ids: selected }),
      }
    )
      .then(async (response) => {
        const data = await response.json().catch(() => null)
        if (!response.ok) {
          setActionError(
            mutationFailureNotice(
              response.status,
              data,
              'The mapping was not confirmed.'
            ).message
          )
          return
        }
        setNotice('Mapping confirmed.')
        setAttempt((value) => value + 1)
      })
      .catch(() => {
        setActionError('The mapping was not confirmed.')
      })
      .finally(() => setBusy(false))
  }

  return (
    <div className="min-w-0 max-w-full overflow-x-hidden p-tc-4 sm:p-tc-7">
      <h1 className="mb-tc-3 text-tc-headline font-semibold text-tc-text">
        Confirm mapping
      </h1>
      <p className="mb-tc-4">
        <Link
          href="/dashboard/questionnaires"
          className="inline-flex min-h-11 items-center text-tc-label text-tc-primary underline"
        >
          Back to questionnaires
        </Link>
      </p>
      {invalidId ? (
        <ErrorState
          failure={failureOf(new Error('invalid questionnaire'))}
          onRetry={() => setAttempt((value) => value + 1)}
        />
      ) : failure ? (
        <ErrorState
          failure={failure}
          onRetry={() => setAttempt((value) => value + 1)}
        />
      ) : loading || authLoading ? (
        <LoadingState
          label="Loading mapping confirmation"
          resetKey={attempt}
          onRetry={() => setAttempt((value) => value + 1)}
        >
          <p className="text-tc-label text-tc-muted">
            Loading suggested mappings.
          </p>
        </LoadingState>
      ) : payload ? (
        <Card>
          <p className="break-all font-medium text-tc-text">
            {payload.filename}
          </p>
          <p className="mt-tc-2 text-tc-label text-tc-muted">
            {payload.display_id}
          </p>
          {payload.needs_review && (
            <p className="mt-tc-3 text-tc-label text-tc-text">
              This questionnaire needs review.
            </p>
          )}
          {payload.items.length === 0 ? (
            <p className="mt-tc-4 text-tc-label text-tc-text">
              Mapping is not ambiguous.
            </p>
          ) : (
            <ul
              className="mt-tc-4 min-w-0 divide-y divide-tc-border"
              aria-label="Suggested mappings"
            >
              {payload.items.map((item) => {
                const control = item.preferred_control_id
                  ? `Control ${item.preferred_control_id}`
                  : 'No control selected'
                const framework = item.preferred_framework_key
                  ? `, ${item.preferred_framework_key}`
                  : ''
                return (
                  <li
                    key={item.id}
                    className="flex min-w-0 items-start gap-tc-3 py-tc-3"
                  >
                    {canEdit && (
                      <input
                        type="checkbox"
                        className="mt-tc-1 h-4 w-4 rounded border-tc-border"
                        checked={selected.includes(item.id)}
                        aria-label={`Select mapping for ${item.question_text}`}
                        onChange={() => {
                          setSelected((current) =>
                            current.includes(item.id)
                              ? current.filter((id) => id !== item.id)
                              : [...current, item.id]
                          )
                        }}
                      />
                    )}
                    <div className="min-w-0">
                      <p className="break-words text-tc-label text-tc-text">
                        {item.question_text}
                      </p>
                      <p className="break-words text-tc-label text-tc-muted">
                        {item.status}. {control}
                        {framework}
                      </p>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          {canEdit && payload.items.length > 0 && (
            <div className="mt-tc-4">
              <Button
                type="button"
                disabled={busy || selected.length === 0}
                onClick={confirm}
              >
                {busy ? 'Confirming' : 'Confirm mapping'}
              </Button>
            </div>
          )}
          {!canEdit && payload.items.length > 0 && (
            <p className="mt-tc-4 text-tc-label text-tc-muted">
              An editor can confirm these mappings.
            </p>
          )}
          {notice && (
            <p role="status" className="mt-tc-3 text-tc-label text-tc-text">
              {notice}
            </p>
          )}
          {actionError && (
            <p role="alert" className="mt-tc-3 text-tc-label text-tc-danger">
              {actionError}
            </p>
          )}
        </Card>
      ) : null}
    </div>
  )
}
