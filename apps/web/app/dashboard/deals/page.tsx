'use client'

import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import {
  ApiRequestError,
  mutationFailureNotice,
  presentHttpFailure,
  type ApiFailurePresentation,
} from '@/lib/api-error'
import {
  DEAL_STAGES,
  parseDeal,
  parseDealList,
  type DealRecord,
  type DealStage,
} from '@/lib/dealConsumer'

const stageLabels: Record<DealStage, string> = {
  prospect: 'Prospect',
  discovery: 'Discovery',
  evaluation: 'Evaluation',
  negotiation: 'Negotiation',
  closed_won: 'Closed won',
  closed_lost: 'Closed lost',
}
const controlClass =
  'w-full rounded-tc-sm border border-tc-border-strong bg-tc-surface-overlay px-tc-3 py-tc-2 text-tc-body text-tc-text disabled:cursor-not-allowed'
type Draft = {
  company_name: string
  buyer_contact_name: string
  buyer_contact_email: string
  deal_value_arr: string
  currency: string
  stage: DealStage
  expected_close_date: string
  actual_close_date: string
  notes: string
}
type Payload = Partial<Draft>
function draftFor(record: DealRecord | null): Draft {
  return {
    company_name: record?.company_name ?? '',
    buyer_contact_name: record?.buyer_contact_name ?? '',
    buyer_contact_email: record?.buyer_contact_email ?? '',
    deal_value_arr: record?.deal_value_arr ?? '',
    currency: record?.currency ?? '',
    stage: record?.stage ?? 'prospect',
    expected_close_date: record?.expected_close_date ?? '',
    actual_close_date: record?.actual_close_date ?? '',
    notes: record?.notes ?? '',
  }
}
function validDate(value: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !value.startsWith('0000') &&
    new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
  )
}
function validate(draft: Draft, initial: Draft, editing: boolean) {
  const errors: Partial<Record<keyof Draft, string>> = {}
  if (!draft.company_name.trim()) errors.company_name = 'Enter a company name.'
  if (
    draft.buyer_contact_email &&
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.buyer_contact_email)
  )
    errors.buyer_contact_email = 'Enter a valid email address.'
  const amount = draft.deal_value_arr.trim()
  if (amount && !/^(0|[1-9]\d{0,15})(\.\d{1,2})?$/.test(amount))
    errors.deal_value_arr =
      'Use a non-negative decimal with up to 16 whole digits and 2 decimal places.'
  if (draft.currency && !/^[A-Z]{3}$/.test(draft.currency))
    errors.currency = 'Use a three-letter uppercase currency code.'
  if (
    amount &&
    !draft.currency &&
    (!editing || amount !== initial.deal_value_arr)
  )
    errors.currency = 'Enter a currency code for this amount.'
  for (const field of ['expected_close_date', 'actual_close_date'] as const) {
    if (draft[field]) {
      try {
        if (!validDate(draft[field])) errors[field] = 'Enter a valid date.'
      } catch {
        errors[field] = 'Enter a valid date.'
      }
    }
  }
  // PATCH ignores nulls: clearing these fields would falsely appear to save.
  if (editing)
    for (const field of [
      'deal_value_arr',
      'currency',
      'expected_close_date',
      'actual_close_date',
    ] as const) {
      if (initial[field] && !draft[field].trim())
        errors[field] =
          'This saved value cannot be cleared here. Enter a replacement.'
    }
  return errors
}
function DealForm({
  record,
  busy,
  error,
  onDirty,
  onCancel,
  onSave,
}: {
  record: DealRecord | null
  busy: boolean
  error: string | null
  onDirty: (dirty: boolean) => void
  onCancel: () => void
  onSave: (body: Payload) => void
}) {
  const [initial] = useState(() => draftFor(record))
  const [draft, setDraft] = useState(initial)
  const [errors, setErrors] = useState<Partial<Record<keyof Draft, string>>>({})
  const prefix = useId()
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)
  function change(field: keyof Draft, value: string) {
    const next = { ...draft, [field]: value }
    setDraft(next)
    onDirty(JSON.stringify(next) !== JSON.stringify(initial))
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const nextErrors = validate(draft, initial, record !== null)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) return
    const body: Payload = {}
    for (const field of Object.keys(draft) as Array<keyof Draft>) {
      const value =
        field === 'deal_value_arr' ? draft[field].trim() : draft[field]
      if (record ? value !== initial[field] : value !== '')
        Object.assign(body, { [field]: value })
    }
    if (record && !Object.keys(body).length) return
    onSave(body)
  }
  return (
    <form onSubmit={submit} noValidate className="space-y-tc-4">
      <p className="text-tc-label text-tc-muted">
        Record the amount in its original currency. No currency conversion is
        applied.
      </p>
      {error && (
        <p role="alert" className="text-tc-label text-tc-danger">
          {error}
        </p>
      )}
      <fieldset
        disabled={busy}
        className="grid min-w-0 grid-cols-1 gap-tc-4 sm:grid-cols-2"
      >
        <legend className="sr-only">Deal details</legend>
        <Input
          label="Company name"
          value={draft.company_name}
          onChange={(e) => change('company_name', e.target.value)}
          required
          maxLength={255}
          error={errors.company_name}
        />
        <div>
          <label
            className="mb-tc-1 block text-tc-label font-medium text-tc-muted"
            htmlFor={`${prefix}-stage`}
          >
            Stage
          </label>
          <select
            id={`${prefix}-stage`}
            className={controlClass}
            value={draft.stage}
            onChange={(e) => change('stage', e.target.value)}
          >
            {DEAL_STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {stageLabels[stage]}
              </option>
            ))}
          </select>
        </div>
        <Input
          label="Buyer contact name"
          value={draft.buyer_contact_name}
          onChange={(e) => change('buyer_contact_name', e.target.value)}
          maxLength={255}
        />
        <Input
          label="Buyer email"
          type="email"
          value={draft.buyer_contact_email}
          onChange={(e) => change('buyer_contact_email', e.target.value)}
          maxLength={255}
          error={errors.buyer_contact_email}
        />
        <Input
          label="ARR amount"
          inputMode="decimal"
          value={draft.deal_value_arr}
          onChange={(e) => change('deal_value_arr', e.target.value)}
          error={errors.deal_value_arr}
        />
        <Input
          label="Currency code"
          placeholder="e.g. USD"
          value={draft.currency}
          onChange={(e) => change('currency', e.target.value)}
          maxLength={3}
          error={errors.currency}
        />
        <Input
          label="Expected close date"
          type="date"
          value={draft.expected_close_date}
          onChange={(e) => change('expected_close_date', e.target.value)}
          error={errors.expected_close_date}
        />
        <Input
          label="Actual close date"
          type="date"
          value={draft.actual_close_date}
          onChange={(e) => change('actual_close_date', e.target.value)}
          error={errors.actual_close_date}
        />
        <div className="sm:col-span-2">
          <label
            className="mb-tc-1 block text-tc-label font-medium text-tc-muted"
            htmlFor={`${prefix}-notes`}
          >
            Notes
          </label>
          <textarea
            id={`${prefix}-notes`}
            rows={3}
            className={controlClass}
            value={draft.notes}
            onChange={(e) => change('notes', e.target.value)}
          />
        </div>
      </fieldset>
      <div className="flex flex-wrap justify-end gap-tc-2">
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          loading={busy}
          disabled={record !== null && !dirty}
        >
          Save deal
        </Button>
      </div>
    </form>
  )
}
type ListState =
  | { kind: 'loading' }
  | { kind: 'ready'; rows: DealRecord[] }
  | { kind: 'error'; failure: ApiFailurePresentation }
function WorkspaceDeals({
  workspaceId,
  canAdmin,
}: {
  workspaceId: number
  canAdmin: boolean
}) {
  const [list, setList] = useState<ListState>({ kind: 'loading' })
  const [revision, setRevision] = useState(0)
  const [editor, setEditor] = useState<DealRecord | 'new' | null>(null)
  const [dirty, setDirty] = useState(false)
  const [discard, setDiscard] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const busy = useRef(false)
  const generation = useRef(0)
  const mutationController = useRef<AbortController | null>(null)
  const retryKeys = useRef(
    new Map<string, { fingerprint: string; key: string }>()
  )
  useEffect(() => {
    generation.current += 1
    return () => {
      generation.current += 1
      mutationController.current?.abort()
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    void (async () => {
      try {
        const response = await fetch('/api/deals', {
          credentials: 'include',
          signal: controller.signal,
        })
        if (!response.ok)
          throw new ApiRequestError(
            presentHttpFailure({ status: response.status })
          )
        let rows: DealRecord[]
        try {
          rows = parseDealList(await response.json())
          if (
            rows.some((row) => row.workspace_id !== workspaceId) ||
            new Set(rows.map((row) => row.id)).size !== rows.length
          )
            throw new Error('Invalid workspace or duplicate deal')
        } catch {
          throw new ApiRequestError(presentHttpFailure({ malformed: true }))
        }
        if (active) setList({ kind: 'ready', rows })
      } catch (reason) {
        if (active)
          setList({
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
  }, [workspaceId, revision])
  useEffect(() => {
    if (!dirty) return
    function preventLoss(event: BeforeUnloadEvent) {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', preventLoss)
    return () => window.removeEventListener('beforeunload', preventLoss)
  }, [dirty])
  function reload() {
    setList({ kind: 'loading' })
    setRevision((value) => value + 1)
  }
  function openEditor(record: DealRecord | 'new') {
    setSaved(false)
    setSaveError(null)
    setDirty(false)
    setEditor(record)
  }
  function close() {
    if (busy.current) return
    if (dirty) setDiscard(true)
    else setEditor(null)
  }
  async function save(body: Payload) {
    if (!canAdmin || busy.current || editor === null) return
    busy.current = true
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    const currentGeneration = generation.current
    const operation = editor === 'new' ? 'new' : String(editor.id)
    const fingerprint = JSON.stringify(body)
    let retry = retryKeys.current.get(operation)
    if (!retry || retry.fingerprint !== fingerprint) {
      retry = { fingerprint, key: crypto.randomUUID() }
      retryKeys.current.set(operation, retry)
    }
    const controller = new AbortController()
    mutationController.current = controller
    try {
      const response = await fetch(
        editor === 'new' ? '/api/deals' : `/api/deals/${editor.id}`,
        {
          method: editor === 'new' ? 'POST' : 'PATCH',
          credentials: 'include',
          signal: controller.signal,
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': retry.key,
          },
          body: fingerprint,
        }
      )
      if (generation.current !== currentGeneration) return
      if (!response.ok) {
        const data: unknown = await response.json().catch(() => null)
        if (generation.current !== currentGeneration) return
        setSaveError(
          mutationFailureNotice(
            response.status,
            data,
            'The deal could not be saved. Your entries are still here.'
          ).message
        )
        return
      }
      const acknowledged = parseDeal(await response.json())
      if (generation.current !== currentGeneration) return
      if (
        acknowledged.workspace_id !== workspaceId ||
        (editor !== 'new' && acknowledged.id !== editor.id)
      )
        throw new Error('Unexpected deal acknowledgment')
      retryKeys.current.delete(operation)
      setEditor(null)
      setDirty(false)
      setSaved(true)
      reload()
    } catch {
      if (generation.current === currentGeneration)
        setSaveError(
          'We could not confirm whether the deal was saved. Your entries are still here. Retry the same entries to check safely.'
        )
    } finally {
      if (generation.current === currentGeneration) {
        busy.current = false
        setSaving(false)
        mutationController.current = null
      }
    }
  }
  return (
    <div className="min-w-0 space-y-tc-4">
      <div className="flex flex-wrap items-start justify-between gap-tc-3">
        <div>
          <h1 className="text-tc-title font-semibold text-tc-text">Deals</h1>
          <p className="mt-tc-1 text-tc-label text-tc-muted">
            Track local deals, their stages, and original currency amounts.
          </p>
        </div>
        {canAdmin && (
          <Button onClick={() => openEditor('new')}>Create deal</Button>
        )}
      </div>
      {saved && (
        <p role="status" className="text-tc-label text-tc-text">
          {list.kind === 'error'
            ? 'Deal saved, but the list could not be refreshed. Try again to load it.'
            : list.kind === 'loading'
              ? 'Deal saved. Refreshing the list…'
              : 'Deal saved.'}
        </p>
      )}
      {list.kind === 'loading' && (
        <LoadingState
          label="Loading deals"
          onRetry={reload}
          resetKey={revision}
        >
          <p className="text-tc-muted">Loading deals…</p>
        </LoadingState>
      )}
      {list.kind === 'error' && (
        <ErrorState failure={list.failure} onRetry={reload} />
      )}
      {list.kind === 'ready' &&
        (list.rows.length === 0 ? (
          <div className="rounded-tc border border-tc-border-strong bg-tc-surface-raised p-tc-6">
            <h2 className="text-tc-body font-semibold text-tc-text">
              No deals yet
            </h2>
            <p className="mt-tc-2 text-tc-label text-tc-muted">
              {canAdmin
                ? 'Create a deal to start tracking this workspace’s pipeline.'
                : 'Deals will appear here when they are added to this workspace.'}
            </p>
          </div>
        ) : (
          <div
            role="region"
            aria-label="Deals list"
            tabIndex={0}
            className="max-w-full overflow-x-auto rounded-tc border border-tc-border-strong"
          >
            <table className="w-full text-left text-tc-label text-tc-text">
              <caption className="sr-only">Deals in this workspace</caption>
              <thead className="bg-tc-surface-raised">
                <tr>
                  {[
                    'Company',
                    'Stage',
                    'ARR amount',
                    'Expected close',
                    'Actual close',
                    ...(canAdmin ? ['Actions'] : []),
                  ].map((label) => (
                    <th
                      scope="col"
                      key={label}
                      className="whitespace-nowrap p-tc-3 font-semibold"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {list.rows.map((row) => (
                  <tr key={row.id} className="border-t border-tc-border-strong">
                    <th
                      scope="row"
                      className="min-w-40 max-w-64 break-words p-tc-3 font-medium"
                    >
                      {row.company_name || 'Unnamed company'}
                      {(row.buyer_contact_name || row.buyer_contact_email) && (
                        <p className="mt-tc-1 font-normal text-tc-muted">
                          {[row.buyer_contact_name, row.buyer_contact_email]
                            .filter(Boolean)
                            .join(' · ')}
                        </p>
                      )}
                    </th>
                    <td className="whitespace-nowrap p-tc-3">
                      {stageLabels[row.stage]}
                    </td>
                    <td className="whitespace-nowrap p-tc-3">
                      {row.deal_value_arr === null
                        ? 'Amount not recorded'
                        : `${row.deal_value_arr}${row.currency ? ` ${row.currency}` : ''}`}
                      {!row.currency && (
                        <p className="text-tc-muted">Currency not recorded</p>
                      )}
                    </td>
                    <td className="whitespace-nowrap p-tc-3">
                      {row.expected_close_date ?? 'Not recorded'}
                    </td>
                    <td className="whitespace-nowrap p-tc-3">
                      {row.actual_close_date ?? 'Not recorded'}
                    </td>
                    {canAdmin && (
                      <td className="p-tc-3">
                        <Button
                          size="sm"
                          variant="secondary"
                          aria-label={`Edit ${row.company_name || 'unnamed company'}`}
                          onClick={() => openEditor(row)}
                        >
                          Edit
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      <Modal
        isOpen={editor !== null}
        onClose={close}
        closeDisabled={saving}
        title={editor === 'new' ? 'Create deal' : 'Edit deal'}
        size="lg"
      >
        {editor !== null && (
          <DealForm
            record={editor === 'new' ? null : editor}
            busy={saving}
            error={saveError}
            onDirty={setDirty}
            onCancel={close}
            onSave={(body) => {
              void save(body)
            }}
          />
        )}
      </Modal>
      <ConfirmDialog
        open={discard}
        title="Discard unsaved changes?"
        description="Your changes have not been saved."
        confirmLabel="Discard changes"
        onClose={() => setDiscard(false)}
        onConfirm={() => {
          setDiscard(false)
          setEditor(null)
          setDirty(false)
          setSaveError(null)
        }}
      />
    </div>
  )
}
export default function DealsPage() {
  const { user, workspace, permissions, loading } = useAuth()
  if (loading) return <p role="status">Loading account…</p>
  if (!user || !workspace || workspace.id <= 0)
    return <p role="status">Choose a workspace to view deals.</p>
  return (
    <WorkspaceDeals
      key={`${user.id}:${workspace.id}:${permissions.can_admin}`}
      workspaceId={workspace.id}
      canAdmin={permissions.can_admin}
    />
  )
}
