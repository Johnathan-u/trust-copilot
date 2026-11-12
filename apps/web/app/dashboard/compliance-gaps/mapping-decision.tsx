'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { Button, ErrorState, LoadingState } from '@/components/ui'
import type { ApiFailurePresentation } from '@/lib/api-error'
import {
  fetchMappingSuggestion,
  postMappingDecision,
} from '@/lib/controlMappingClient'
import {
  parseControlIdText,
  type MappingDecision,
  type MappingSuggestion,
} from '@/lib/controlMappingConsumer'
import { failureOf } from '@/lib/section-load'

const STATE_LABELS = {
  proposed: 'Proposed',
  confirmed: 'Confirmed',
  overridden: 'Overridden',
} as const

const fieldClass =
  'min-h-11 w-full rounded-tc border border-tc-border-strong bg-tc-surface px-3 text-tc-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-tc-primary'

type Loaded = {
  question: string
  data: MappingSuggestion | MappingDecision | null
  failure: ApiFailurePresentation | null
}

function held(data: MappingSuggestion | MappingDecision): boolean {
  return 'precedence_held' in data && data.precedence_held
}

export function MappingDecision({
  question,
  canAdmin,
}: {
  question: string
  canAdmin: boolean
}) {
  const rationaleId = useId()
  const controlId = useId()
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Loaded | null>(null)
  const [actionFailure, setActionFailure] =
    useState<ApiFailurePresentation | null>(null)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState({
    signature: '',
    controlIds: '',
    rationale: '',
  })
  const [seenQuestion, setSeenQuestion] = useState(question)
  const keys = useRef(new Map<string, string>())
  const mounted = useRef(true)
  if (seenQuestion !== question) {
    setSeenQuestion(question)
    setActionFailure(null)
  }

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!question.trim()) return
    let active = true
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    void (async () => {
      await Promise.resolve()
      if (!active) return
      try {
        const data = await fetchMappingSuggestion(question, controller.signal)
        if (active && !controller.signal.aborted)
          setResult({ question, data, failure: null })
      } catch (error: unknown) {
        if (active && !controller.signal.aborted)
          setResult({ question, data: null, failure: failureOf(error) })
      } finally {
        clearTimeout(timeout)
      }
    })()
    return () => {
      active = false
      clearTimeout(timeout)
      controller.abort()
    }
  }, [question, attempt])

  const current = result?.question === question ? result : null
  const data = current?.data ?? null
  const signature = data
    ? `${question}|${data.state}|${String(data.version)}|${data.control_ids.join(',')}`
    : ''
  if (signature && draft.signature !== signature) {
    setDraft({
      signature,
      controlIds: data ? data.control_ids.join(', ') : '',
      rationale: '',
    })
  }

  async function run(
    action: 'confirm' | 'override' | 'rollback',
    body: { question: string; control_ids?: number[]; rationale?: string },
    signatureKey: string
  ) {
    if (busy) return
    let key = keys.current.get(signatureKey)
    if (!key) {
      key = crypto.randomUUID()
      keys.current.set(signatureKey, key)
    }
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    setBusy(true)
    setActionFailure(null)
    try {
      const decision = await postMappingDecision(
        action,
        body,
        key,
        controller.signal
      )
      keys.current.delete(signatureKey)
      if (mounted.current)
        setResult({ question, data: decision, failure: null })
    } catch (error: unknown) {
      if (mounted.current) setActionFailure(failureOf(error))
    } finally {
      clearTimeout(timeout)
      if (mounted.current) setBusy(false)
    }
  }

  if (!question.trim())
    return <p className="text-tc-muted">This question has no text to map.</p>
  if (!current || (!current.failure && !current.data))
    return (
      <LoadingState
        label="Loading control mapping"
        onRetry={() => setAttempt((value) => value + 1)}
        resetKey={attempt}
      />
    )
  if (current.failure || !data)
    return (
      <ErrorState
        failure={
          current.failure ?? {
            kind: 'rejected',
            title: 'Could not load this',
            description: 'The request did not succeed. Try again.',
          }
        }
        onRetry={() => {
          setResult(null)
          setAttempt((value) => value + 1)
        }}
      />
    )

  const overrideIds = parseControlIdText(draft.controlIds)
  const rationale = draft.rationale.trim()
  return (
    <section aria-label="Control mapping" className="space-y-3 pt-2">
      <h3 className="text-sm font-semibold text-tc-text">Control mapping</h3>
      <dl className="grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="text-tc-muted">State</dt>
          <dd className="font-semibold text-tc-text">
            {STATE_LABELS[data.state]}
          </dd>
        </div>
        <div>
          <dt className="text-tc-muted">Version</dt>
          <dd className="text-tc-text">
            {data.version === null ? 'Not saved' : data.version}
          </dd>
        </div>
        <div>
          <dt className="text-tc-muted">Rationale</dt>
          <dd className="break-words text-tc-text">
            {data.rationale?.trim() ? data.rationale : 'None recorded'}
          </dd>
        </div>
        <div>
          <dt className="text-tc-muted">Precedence</dt>
          <dd className="text-tc-text">{data.precedence}</dd>
        </div>
      </dl>
      <p className="text-tc-muted">
        An override outranks a confirmation, which outranks a proposal.
      </p>
      {data.control_ids.length ? (
        <ul className="list-disc space-y-1 pl-5 text-tc-text">
          {data.control_ids.map((id, index) => (
            <li key={`${id}:${index}`}>Control {id}</li>
          ))}
        </ul>
      ) : (
        <p className="text-tc-muted">No controls are selected.</p>
      )}
      {held(data) ? (
        <p role="status" className="text-tc-text">
          This mapping stays overridden. A confirmation does not replace an
          override.
        </p>
      ) : null}
      {actionFailure ? (
        <p role="alert" className="text-tc-text">
          {actionFailure.description}
        </p>
      ) : null}
      {canAdmin ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={busy}
              onClick={() =>
                void run(
                  'confirm',
                  { question, control_ids: data.control_ids },
                  `confirm:${question}:${data.control_ids.join(',')}`
                )
              }
            >
              Confirm mapping
            </Button>
            {data.version !== null ? (
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  void run('rollback', { question }, `rollback:${question}`)
                }
              >
                Roll back mapping
              </Button>
            ) : null}
          </div>
          <div className="space-y-2">
            <label htmlFor={controlId} className="block text-tc-text">
              Override control ids
            </label>
            <input
              id={controlId}
              className={fieldClass}
              value={draft.controlIds}
              autoComplete="off"
              onChange={(event) =>
                setDraft((currentDraft) => ({
                  ...currentDraft,
                  controlIds: event.target.value,
                }))
              }
            />
            {overrideIds === null ? (
              <p role="alert" className="text-tc-muted">
                Enter control ids as whole numbers, separated by commas.
              </p>
            ) : null}
            <label htmlFor={rationaleId} className="block text-tc-text">
              Override rationale
            </label>
            <textarea
              id={rationaleId}
              className={fieldClass}
              value={draft.rationale}
              onChange={(event) =>
                setDraft((currentDraft) => ({
                  ...currentDraft,
                  rationale: event.target.value,
                }))
              }
            />
            <Button
              type="button"
              disabled={busy || !rationale || overrideIds === null}
              onClick={() => {
                if (!rationale || overrideIds === null) return
                void run(
                  'override',
                  {
                    question,
                    control_ids: overrideIds,
                    rationale,
                  },
                  `override:${question}:${overrideIds.join(',')}:${rationale}`
                )
              }}
            >
              Save override
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-tc-muted">
          An administrator can confirm, override, or roll back this mapping.
        </p>
      )}
    </section>
  )
}
