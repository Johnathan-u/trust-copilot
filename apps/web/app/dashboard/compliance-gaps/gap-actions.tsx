'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { Button, Dialog, ErrorState, LoadingState } from '@/components/ui'
import {
  failureOf,
  readSectionJson,
  recordFromPayload,
} from '@/lib/section-load'
import type { ApiFailurePresentation } from '@/lib/api-error'
import { parseGaps, positiveId, type Gap } from './gap-contract'

export type GapIntent =
  { kind: 'accepted' | 'dismissed' } | { kind: 'resolve'; evidenceId: number }

function rejection(status: number) {
  if (status === 401 || status === 403)
    return 'You no longer have permission to perform this action. Refresh the page to check your access.'
  if (status === 404)
    return 'The gap or selected evidence is no longer available in this workspace. Refresh the page before trying again.'
  if (status === 409)
    return 'This gap changed or another request is still running. Refresh the gaps to review its current status before trying again.'
  if (status === 400 || status === 422)
    return 'This evidence cannot resolve the gap. Choose approved, current evidence that is linked to the relevant control or question.'
  return 'Could not confirm the action. Your choice is kept; retry to check the same request safely.'
}

export function useGapMutation(
  gapId: number,
  workspaceId: number,
  onConfirmed: (gap: Gap, notificationFailed: boolean) => void
) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const intentKeys = useRef(new Map<string, string>())
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      controller.current?.abort()
      if (timer.current) clearTimeout(timer.current)
    }
  }, [])
  async function submit(intent: GapIntent) {
    if (controller.current) return
    const body =
      intent.kind === 'resolve'
        ? { evidence_id: intent.evidenceId }
        : { status: intent.kind }
    const signature = JSON.stringify({ gapId, workspaceId, ...body })
    let key = intentKeys.current.get(signature)
    if (!key) {
      key = crypto.randomUUID()
      intentKeys.current.set(signature, key)
    }
    const request = new AbortController()
    controller.current = request
    timer.current = setTimeout(() => request.abort(), 15000)
    setBusy(true)
    setError(null)
    try {
      const response = await fetch(
        `/api/evidence-gaps/${gapId}/${intent.kind === 'resolve' ? 'resolve' : 'decision'}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': key,
          },
          signal: request.signal,
          body: JSON.stringify(body),
        }
      )
      if (!response.ok) {
        if (mounted.current && !request.signal.aborted)
          setError(rejection(response.status))
        return
      }
      const payload = recordFromPayload(await readSectionJson(response))
      const updated = parseGaps({
        schema_version: 'evidence-gap-ownership/v1',
        gaps: [payload],
      })[0]
      if (
        updated.id !== gapId ||
        updated.workspace_id !== workspaceId ||
        updated.status !==
          (intent.kind === 'resolve' ? 'resolved' : intent.kind) ||
        (intent.kind === 'resolve' &&
          (payload.resolved !== true || typeof payload.notified !== 'boolean'))
      )
        throw new Error('Unconfirmed result')
      if (mounted.current && !request.signal.aborted)
        onConfirmed(
          updated,
          intent.kind === 'resolve' && payload.notified === false
        )
    } catch {
      if (mounted.current) setError(rejection(0))
    } finally {
      if (timer.current) clearTimeout(timer.current)
      controller.current = null
      if (mounted.current) setBusy(false)
    }
  }
  return { busy, error, submit }
}

type EvidenceChoice = {
  id: number
  title: string
  source_type: string
  approval_status: 'approved'
  created_at: string | null
}
type EvidencePage = {
  total: number
  offset: number
  limit: number
  items: EvidenceChoice[]
}
export function parseEvidenceChoices(input: unknown): EvidencePage {
  const data = recordFromPayload(input)
  if (
    !Number.isSafeInteger(data.total) ||
    Number(data.total) < 0 ||
    !Number.isSafeInteger(data.offset) ||
    Number(data.offset) < 0 ||
    !positiveId(data.limit) ||
    !Array.isArray(data.items) ||
    data.items.length > Number(data.limit) ||
    data.items.length > Number(data.total)
  )
    throw new Error('Invalid evidence results')
  const ids = new Set<number>()
  for (const value of data.items) {
    const item = recordFromPayload(value)
    if (
      !positiveId(item.id) ||
      ids.has(Number(item.id)) ||
      typeof item.title !== 'string' ||
      typeof item.source_type !== 'string' ||
      item.approval_status !== 'approved' ||
      (item.created_at !== null &&
        (typeof item.created_at !== 'string' ||
          !Number.isFinite(Date.parse(item.created_at))))
    )
      throw new Error('Invalid evidence choice')
    ids.add(Number(item.id))
  }
  return data as EvidencePage
}

const fieldClass =
  'min-h-11 w-full rounded-tc border border-tc-border-strong bg-tc-surface px-3 text-tc-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-tc-primary'

function EvidencePicker({
  controlId,
  busy,
  selected,
  onSelect,
}: {
  controlId: number | null
  busy: boolean
  selected: EvidenceChoice | null
  onSelect: (choice: EvidenceChoice | null) => void
}) {
  const fieldId = useId()
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState({ title: '', offset: 0, attempt: 0 })
  const [page, setPage] = useState<EvidencePage | null>(null)
  const [failure, setFailure] = useState<ApiFailurePresentation | null>(null)
  useEffect(() => {
    let active = true
    const request = new AbortController()
    const timeout = setTimeout(() => request.abort(), 15000)
    const params = new URLSearchParams({
      approval_status: 'approved',
      limit: '25',
      offset: String(search.offset),
    })
    if (controlId !== null) params.set('control_id', String(controlId))
    if (search.title) params.set('title_query', search.title)
    void (async () => {
      try {
        const result = parseEvidenceChoices(
          await readSectionJson(
            await fetch(`/api/evidence-search?${params}`, {
              credentials: 'include',
              signal: request.signal,
            })
          )
        )
        if (active) setPage(result)
      } catch (error) {
        if (active) setFailure(failureOf(error))
      } finally {
        clearTimeout(timeout)
      }
    })()
    return () => {
      active = false
      request.abort()
      clearTimeout(timeout)
    }
  }, [controlId, search])
  function load(title: string, offset: number) {
    setPage(null)
    setFailure(null)
    setSearch((previous) => ({ title, offset, attempt: previous.attempt + 1 }))
  }
  return (
    <div className="space-y-3">
      <p className="text-tc-label text-tc-muted">
        Choose approved evidence from this workspace. The server also checks
        freshness and its link to this gap before resolving it.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 space-y-1 text-tc-label text-tc-text">
          Search evidence titles
          <input
            className={fieldClass}
            value={query}
            disabled={busy}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                load(query.trim(), 0)
              }
            }}
          />
        </label>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => load(query.trim(), 0)}
        >
          Search evidence
        </Button>
      </div>
      {failure ? (
        <ErrorState
          failure={failure}
          onRetry={() => load(search.title, search.offset)}
        />
      ) : !page ? (
        <LoadingState
          label="Loading evidence choices"
          onRetry={() => load(search.title, search.offset)}
        />
      ) : (
        <>
          {page.items.length ? (
            <fieldset disabled={busy} className="space-y-2">
              <legend className="mb-2 text-tc-label font-semibold text-tc-text">
                Evidence choices
              </legend>
              {page.items.map((choice) => (
                <label
                  key={choice.id}
                  className="flex min-h-11 items-start gap-2 rounded-tc border border-tc-border p-3 text-tc-label text-tc-text"
                >
                  <input
                    type="radio"
                    className="mt-1 shrink-0"
                    name={fieldId}
                    checked={selected?.id === choice.id}
                    onChange={() => onSelect(choice)}
                  />
                  <span className="min-w-0 break-words">
                    {choice.title.trim() || 'Untitled evidence'}
                    <span className="block text-tc-muted">
                      {choice.created_at
                        ? `Added ${new Date(choice.created_at).toLocaleString()}`
                        : 'Date unavailable'}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : (
            <p role="status" className="text-tc-label text-tc-muted">
              No approved evidence matches this search.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              disabled={busy || search.offset === 0}
              onClick={() =>
                load(search.title, Math.max(0, search.offset - 25))
              }
            >
              Previous evidence
            </Button>
            <span className="text-tc-label text-tc-muted">
              {page.total} results
            </span>
            <Button
              variant="secondary"
              disabled={busy || search.offset + 25 >= page.total}
              onClick={() => load(search.title, search.offset + 25)}
            >
              Next evidence
            </Button>
          </div>
        </>
      )}
      {selected ? (
        <p className="break-words text-tc-label text-tc-text">
          Selected evidence: {selected.title.trim() || 'Untitled evidence'}
        </p>
      ) : null}
    </div>
  )
}

export function GapActionDialog({
  gap,
  kind,
  onClose,
  onConfirmed,
}: {
  gap: Gap
  kind: GapIntent['kind']
  onClose: () => void
  onConfirmed: (gap: Gap, notificationFailed: boolean) => void
}) {
  const [selected, setSelected] = useState<EvidenceChoice | null>(null)
  const mutation = useGapMutation(gap.id, gap.workspace_id, onConfirmed)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const title =
    kind === 'resolve'
      ? 'Resolve gap with evidence'
      : kind === 'accepted'
        ? 'Accept this gap?'
        : 'Dismiss this gap?'
  const description =
    kind === 'resolve'
      ? 'Resolution closes the open gap only after the server confirms qualifying evidence.'
      : kind === 'accepted'
        ? 'Accepting records an administrative decision and closes the gap to further actions. It does not verify evidence or resolve the missing evidence.'
        : 'Dismissing records an administrative decision and closes the gap to further actions. It does not verify evidence or establish compliance.'
  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      description={description}
      closeDisabled={mutation.busy}
      initialFocusRef={cancelRef}
    >
      <div className="space-y-4">
        <p className="break-words text-tc-body font-semibold text-tc-text">
          {gap.suggested_evidence_doc_title || 'Evidence gap'}
        </p>
        {kind === 'resolve' ? (
          <EvidencePicker
            controlId={gap.control_id}
            busy={mutation.busy}
            selected={selected}
            onSelect={setSelected}
          />
        ) : null}
        {gap.status !== 'open' ? (
          <p role="status" className="text-tc-label text-tc-text">
            This gap is no longer open. Close this dialog to review its current
            status.
          </p>
        ) : null}
        {mutation.error ? (
          <p role="alert" className="text-tc-label text-tc-text">
            {mutation.error}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            ref={cancelRef}
            variant="secondary"
            disabled={mutation.busy}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            disabled={
              mutation.busy ||
              gap.status !== 'open' ||
              (kind === 'resolve' && !selected)
            }
            onClick={() => {
              if (kind === 'resolve') {
                if (selected)
                  void mutation.submit({ kind, evidenceId: selected.id })
              } else void mutation.submit({ kind })
            }}
          >
            {mutation.busy
              ? 'Saving…'
              : kind === 'resolve'
                ? 'Resolve with selected evidence'
                : kind === 'accepted'
                  ? 'Confirm accept'
                  : 'Confirm dismiss'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
