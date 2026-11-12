'use client'

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import {
  ApiRequestError,
  mutationFailureNotice,
  presentHttpFailure,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import {
  parseDeal,
  parseDealRisk,
  parseDealRoom,
  type DealRecord,
  type DealRoomQuestion,
} from '@/lib/dealConsumer'

const stageLabels: Record<DealRecord['stage'], string> = {
  prospect: 'Prospect',
  discovery: 'Discovery',
  evaluation: 'Evaluation',
  negotiation: 'Negotiation',
  closed_won: 'Closed won',
  closed_lost: 'Closed lost',
}
const statusLabels: Record<DealRoomQuestion['answer_status'], string> = {
  proven: 'Proven',
  draft: 'Draft',
  pending: 'Pending',
}

type Section<T> =
  | { kind: 'loading' }
  | { kind: 'ready'; value: T }
  | { kind: 'error'; failure: ApiFailurePresentation }

function readQuestionnaireId(value: string): number | null {
  const trimmed = value.trim()
  if (!/^[1-9]\d{0,15}$/.test(trimmed)) return null
  const id = Number(trimmed)
  if (!Number.isSafeInteger(id) || id < 1) return null
  return id
}

function useDealRead<T extends { deal_id: number }>(
  path: string,
  parse: (value: unknown) => T,
  dealId: number,
  workspaceId: number,
  dealWorkspaceId: number
) {
  const [tick, setTick] = useState(0)
  const [state, setState] = useState<Section<T>>({ kind: 'loading' })
  useEffect(() => {
    if (dealWorkspaceId !== workspaceId) return
    const controller = new AbortController()
    let active = true
    void (async () => {
      try {
        const response = await fetch(path, {
          credentials: 'include',
          signal: controller.signal,
        })
        if (!active) return
        if (!response.ok)
          throw new ApiRequestError(
            presentHttpFailure({ status: response.status })
          )
        let body: unknown
        try {
          body = await response.json()
        } catch {
          throw new ApiRequestError(presentHttpFailure({ malformed: true }))
        }
        let value: T
        try {
          value = parse(body)
        } catch {
          throw new ApiRequestError(presentHttpFailure({ malformed: true }))
        }
        if (!active) return
        if (value.deal_id !== dealId)
          throw new ApiRequestError(presentHttpFailure({ malformed: true }))
        setState({ kind: 'ready', value })
      } catch (reason) {
        if (!active) return
        setState({
          kind: 'error',
          failure:
            reason instanceof ApiRequestError
              ? reason.failure
              : presentHttpFailure({ offline: true }),
        })
      }
    })()
    return () => {
      active = false
      controller.abort()
    }
  }, [path, parse, dealId, workspaceId, dealWorkspaceId, tick])
  function retry() {
    setState({ kind: 'loading' })
    setTick((value) => value + 1)
  }
  return { state, retry }
}

function SectionBody<T>({
  state,
  label,
  onRetry,
  children,
}: {
  state: Section<T>
  label: string
  onRetry: () => void
  children: (value: T) => ReactNode
}) {
  if (state.kind === 'loading') {
    return (
      <LoadingState label={label} onRetry={onRetry}>
        <p className="text-tc-muted">{label}…</p>
      </LoadingState>
    )
  }
  if (state.kind === 'error') {
    return <ErrorState failure={state.failure} onRetry={onRetry} />
  }
  return children(state.value)
}

export function DealLinksPanel({
  deal,
  workspaceId,
  canAdmin,
  onDirty,
  onBusy,
  onClose,
  onLinkAttempt,
  onLinked,
}: {
  deal: DealRecord
  workspaceId: number
  canAdmin: boolean
  onDirty: (dirty: boolean) => void
  onBusy: (busy: boolean) => void
  onClose: () => void
  onLinkAttempt: () => void
  onLinked: (questionnaireId: number) => void
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  const busy = useRef(false)
  const generation = useRef(0)
  const linkAbort = useRef<AbortController | null>(null)
  const retryKeys = useRef(
    new Map<string, { fingerprint: string; key: string }>()
  )
  const [draft, setDraft] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const company = deal.company_name || 'unnamed company'
  const risk = useDealRead(
    `/api/deals/${deal.id}/risk`,
    parseDealRisk,
    deal.id,
    workspaceId,
    deal.workspace_id
  )
  const room = useDealRead(
    `/api/deals/${deal.id}/room`,
    parseDealRoom,
    deal.id,
    workspaceId,
    deal.workspace_id
  )
  useEffect(() => {
    headingRef.current?.focus()
  }, [])
  useEffect(() => {
    generation.current += 1
    return () => {
      generation.current += 1
      linkAbort.current?.abort()
    }
  }, [workspaceId, deal.id])
  useEffect(() => {
    onBusy(saving)
  }, [saving, onBusy])
  useEffect(() => () => onBusy(false), [onBusy])
  function change(value: string) {
    setDraft(value)
    onDirty(value !== '')
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!canAdmin || busy.current) return
    const questionnaireId = readQuestionnaireId(draft)
    if (questionnaireId == null) {
      setFieldError('Enter a positive whole questionnaire id.')
      return
    }
    setFieldError(null)
    busy.current = true
    setSaving(true)
    setSaveError(null)
    onLinkAttempt()
    const currentGeneration = generation.current
    const operation = String(deal.id)
    const fingerprint = JSON.stringify({ questionnaire_id: questionnaireId })
    let retry = retryKeys.current.get(operation)
    if (!retry || retry.fingerprint !== fingerprint) {
      retry = { fingerprint, key: crypto.randomUUID() }
      retryKeys.current.set(operation, retry)
    }
    const controller = new AbortController()
    linkAbort.current = controller
    try {
      const response = await fetch(`/api/deals/${deal.id}/link-questionnaire`, {
        method: 'POST',
        credentials: 'include',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': retry.key,
        },
        body: fingerprint,
      })
      if (generation.current !== currentGeneration) return
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null)
        if (generation.current !== currentGeneration) return
        setSaveError(
          mutationFailureNotice(
            response.status,
            data,
            'The questionnaire could not be linked. The id is still here.'
          ).message
        )
        return
      }
      let acknowledged: DealRecord
      try {
        acknowledged = parseDeal(await response.json())
      } catch {
        throw new Error('malformed acknowledgment')
      }
      if (generation.current !== currentGeneration) return
      if (
        acknowledged.workspace_id !== workspaceId ||
        acknowledged.id !== deal.id ||
        !acknowledged.linked_questionnaire_ids.includes(questionnaireId)
      )
        throw new Error('unexpected acknowledgment')
      retryKeys.current.delete(operation)
      setDraft('')
      onDirty(false)
      onLinked(questionnaireId)
    } catch {
      if (generation.current === currentGeneration)
        setSaveError(
          'We could not confirm whether the questionnaire was linked. The id is still here. Retry the same id to check safely.'
        )
    } finally {
      if (generation.current === currentGeneration) {
        busy.current = false
        setSaving(false)
        linkAbort.current = null
      }
    }
  }
  return (
    <section
      aria-label="Deal links and risk"
      className="min-w-0 space-y-tc-4 break-words rounded-tc border border-tc-border-strong bg-tc-surface-raised p-tc-4"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !saving) onClose()
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-tc-3">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="text-tc-body font-semibold text-tc-text"
        >
          Links and risk for {company}
        </h2>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={saving}
          onClick={onClose}
        >
          Close links and risk
        </Button>
      </div>
      <div className="space-y-tc-2">
        <h3 className="text-tc-label font-semibold text-tc-text">
          Linked questionnaires
        </h3>
        {deal.linked_questionnaire_ids.length === 0 ? (
          <p className="text-tc-label text-tc-muted">
            No questionnaires are linked to this deal.
          </p>
        ) : (
          <ul className="list-disc space-y-tc-1 pl-tc-5 text-tc-label text-tc-text">
            {deal.linked_questionnaire_ids.map((id) => (
              <li key={id}>Questionnaire {id}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-tc-2">
        <h3 className="text-tc-label font-semibold text-tc-text">
          Scoped risk
        </h3>
        <SectionBody
          state={risk.state}
          label="Loading scoped risk"
          onRetry={risk.retry}
        >
          {(value) => (
            <dl className="space-y-tc-2 text-tc-label text-tc-text">
              <div>
                <dt className="text-tc-muted">Scored company</dt>
                <dd>{value.company_name || 'Unnamed company'}</dd>
              </div>
              <div>
                <dt className="text-tc-muted">Deal stage</dt>
                <dd>{stageLabels[value.stage]}</dd>
              </div>
              <div>
                <dt className="text-tc-muted">Risk score</dt>
                <dd>{value.risk_score}</dd>
              </div>
              <div>
                <dt className="text-tc-muted">Revenue at risk</dt>
                <dd>
                  {value.revenue_at_risk ?? 'Revenue at risk is not recorded'}
                </dd>
              </div>
              {(
                [
                  [
                    'Unanswered questions',
                    value.breakdown.unanswered_questions,
                  ],
                  [
                    'Low-confidence answers',
                    value.breakdown.low_confidence_answers,
                  ],
                  ['Unapproved answers', value.breakdown.unapproved_answers],
                  ['Stale evidence', value.breakdown.stale_evidence],
                  ['Questions in scope', value.breakdown.total_questions],
                ] as const
              ).map(([label, count]) => (
                <div key={label}>
                  <dt className="text-tc-muted">{label}</dt>
                  <dd>{count}</dd>
                </div>
              ))}
            </dl>
          )}
        </SectionBody>
      </div>
      <div className="space-y-tc-2">
        <h3 className="text-tc-label font-semibold text-tc-text">Deal room</h3>
        <SectionBody
          state={room.state}
          label="Loading deal room"
          onRetry={room.retry}
        >
          {(value) => (
            <div className="space-y-tc-3 text-tc-label text-tc-text">
              {value.questionnaires.length === 0 ? (
                <p className="text-tc-muted">
                  No questionnaires from this workspace are in the room.
                </p>
              ) : (
                <ul className="space-y-tc-3">
                  {value.questionnaires.map((item) => (
                    <li key={item.questionnaire_id} className="break-words">
                      <p className="font-medium">{item.name}</p>
                      <p className="text-tc-muted">
                        Proven {item.proven}, pending {item.pending}, of{' '}
                        {item.total}
                      </p>
                      {item.questions.length > 0 && (
                        <ul className="mt-tc-1 list-disc space-y-tc-1 pl-tc-5">
                          {item.questions.map((question) => (
                            <li
                              key={question.question_id}
                              className="break-words"
                            >
                              {question.text}{' '}
                              {statusLabels[question.answer_status]}
                              {question.answer_text && (
                                <p className="break-words text-tc-muted">
                                  {question.answer_text}
                                </p>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {value.trust_center_articles.length === 0 ? (
                <p className="text-tc-muted">
                  No published trust center articles are in the room.
                </p>
              ) : (
                <ul className="list-disc space-y-tc-1 pl-tc-5">
                  {value.trust_center_articles.map((article) => (
                    <li key={article.id} className="break-words">
                      {article.title}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </SectionBody>
      </div>
      {canAdmin && (
        <form onSubmit={submit} noValidate className="space-y-tc-3">
          {saveError && (
            <p role="alert" className="text-tc-label text-tc-danger">
              {saveError}
            </p>
          )}
          <fieldset disabled={saving} className="min-w-0 space-y-tc-3">
            <legend className="text-tc-label font-semibold text-tc-text">
              Link a questionnaire
            </legend>
            <Input
              label="Questionnaire id"
              inputMode="numeric"
              autoComplete="off"
              value={draft}
              onChange={(event) => change(event.target.value)}
              error={fieldError}
            />
            <Button type="submit" loading={saving}>
              Link questionnaire
            </Button>
          </fieldset>
        </form>
      )}
    </section>
  )
}
