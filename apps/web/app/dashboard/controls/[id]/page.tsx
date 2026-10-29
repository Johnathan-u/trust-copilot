'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { presentHttpFailure } from '@/lib/api-error'
import { parseCoverageResponse } from '@/lib/coverageConsumer'
import { readSectionJson, sectionFailure } from '@/lib/section-load'
import {
  evaluationLabel,
  fieldClass,
  lifecycleLabels,
  linkClass,
  readControl,
  readEvidence,
  readMembers,
  ruleLabels,
  useResource,
  type Control,
  type EvidenceLink,
  type Member,
} from '../control-data'

export default function ControlDetailPage() {
  const auth = useAuth()
  const { id } = useParams<{ id: string }>()
  if (!auth.permissions.can_review)
    return (
      <ErrorState
        failure={presentHttpFailure({ status: 403 })}
        onRetry={() => void auth.refresh()}
      />
    )
  if (!/^\d+$/.test(id) || !Number.isSafeInteger(Number(id)) || Number(id) <= 0)
    return (
      <ErrorState
        failure={presentHttpFailure({ status: 404 })}
        onRetry={() => void auth.refresh()}
      />
    )
  return (
    <ControlDetail
      key={`${auth.workspace?.id}:${auth.permissions.can_admin}:${id}`}
      id={id}
      canAdmin={auth.permissions.can_admin}
    />
  )
}

function ControlDetail({ id, canAdmin }: { id: string; canAdmin: boolean }) {
  const control = useResource(`/api/compliance/controls/${id}`, readControl)
  const evidence = useResource(
    `/api/compliance/controls/${id}/evidence`,
    readEvidence
  )
  const coverage = useResource(
    `/api/compliance-coverage?control_id=${id}`,
    parseCoverageResponse
  )
  const members = useResource(canAdmin ? '/api/members' : null, readMembers)
  if (!control.result)
    return (
      <LoadingState
        label="Loading control"
        onRetry={control.reload}
        resetKey={control.attempt}
      >
        <p className="text-tc-muted">Loading control…</p>
      </LoadingState>
    )
  if (!control.result.ok)
    return (
      <ErrorState
        failure={sectionFailure(control.result)}
        onRetry={control.reload}
        secondary={
          <Link className={linkClass} href="/dashboard/controls">
            Back to control library
          </Link>
        }
      />
    )
  const row = control.result.data
  const explanation = coverage.result?.ok
    ? coverage.result.data.control_coverage.explanations.find(
        (item) => item.control_id === row.id
      )
    : undefined
  return (
    <div className="min-w-0 space-y-6 pb-8">
      <header className="space-y-2">
        <Link className={linkClass} href="/dashboard/controls">
          Back to control library
        </Link>
        <h1 className="break-words text-tc-headline font-semibold text-tc-text">
          {row.name || 'Untitled control'}
        </h1>
        <p className="text-tc-muted">
          {row.framework || 'Custom control'}
          {row.category ? ` · ${row.category}` : ''}
        </p>
      </header>
      <section aria-labelledby="evaluation-heading">
        <Card className="space-y-2 p-4">
          <h2
            id="evaluation-heading"
            className="text-tc-title font-semibold text-tc-text"
          >
            Evidence evaluation
          </h2>
          {!coverage.result ? (
            <LoadingState
              label="Loading evaluation"
              onRetry={coverage.reload}
              resetKey={coverage.attempt}
            />
          ) : !coverage.result.ok ? (
            <>
              <p role="status" className="text-tc-text">
                Evaluation unavailable
              </p>
              <Button variant="secondary" onClick={coverage.reload}>
                Retry evaluation
              </Button>
            </>
          ) : (
            <>
              <p className="font-semibold text-tc-text">
                {evaluationLabel(explanation)}
              </p>
              <p className="text-tc-muted">
                {explanation
                  ? ruleLabels[explanation.rule] ||
                    'The evaluation needs further review.'
                  : 'No current evaluation was returned.'}
              </p>
            </>
          )}
          <p className="text-tc-label text-tc-muted">
            Evidence eligibility is evaluated separately from the control
            lifecycle. Neither is a certification or a guarantee of compliance.
          </p>
        </Card>
      </section>
      <section aria-labelledby="ownership-heading" className="space-y-3">
        <h2
          id="ownership-heading"
          className="text-tc-title font-semibold text-tc-text"
        >
          Ownership and lifecycle
        </h2>
        {canAdmin ? (
          <ControlForm
            control={row}
            members={members.result?.ok ? members.result.data : []}
            membersReady={Boolean(members.result?.ok)}
          />
        ) : (
          <Card className="space-y-2 p-4">
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-tc-muted">Lifecycle</dt>
                <dd className="text-tc-text">
                  {lifecycleLabels[row.canonical.lifecycle]}
                </dd>
              </div>
              <div>
                <dt className="text-tc-muted">Owner</dt>
                <dd className="text-tc-text">
                  {row.canonical.owner_team ||
                    (row.canonical.owner_user_id
                      ? 'Assigned member'
                      : 'Unassigned')}
                </dd>
              </div>
            </dl>
            <p className="text-tc-label text-tc-muted">
              A workspace administrator can update ownership and lifecycle.
            </p>
          </Card>
        )}
        {canAdmin && members.result && !members.result.ok ? (
          <div className="space-y-2 rounded-tc border border-tc-border p-3">
            <p role="status" className="text-tc-muted">
              Member names are unavailable. Existing ownership is preserved.
            </p>
            <Button variant="secondary" onClick={members.reload}>
              Retry members
            </Button>
          </div>
        ) : null}
      </section>
      <section aria-labelledby="evidence-heading" className="space-y-3">
        <h2
          id="evidence-heading"
          className="text-tc-title font-semibold text-tc-text"
        >
          Backing evidence
        </h2>
        <p className="text-tc-label text-tc-muted">
          Review each linked item. Evidence-link verification does not change
          the control lifecycle or replace evidence approval.
        </p>
        {!evidence.result ? (
          <LoadingState
            label="Loading backing evidence"
            onRetry={evidence.reload}
            resetKey={evidence.attempt}
          />
        ) : !evidence.result.ok ? (
          <ErrorState
            failure={sectionFailure(evidence.result)}
            onRetry={evidence.reload}
          />
        ) : evidence.result.data.length === 0 ? (
          <EmptyState
            title="No backing evidence"
            description="No evidence is linked to this control. Its lifecycle alone does not demonstrate an evidence pass."
          />
        ) : (
          <ul className="grid gap-3">
            {evidence.result.data.map((link) => (
              <li key={link.id}>
                <EvidenceReview controlId={id} initial={link} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function ControlForm({
  control,
  members,
  membersReady,
}: {
  control: Control
  members: Member[]
  membersReady: boolean
}) {
  const router = useRouter()
  const [baseline, setBaseline] = useState(control.canonical)
  const [owner, setOwner] = useState(
    control.canonical.owner_user_id?.toString() ?? ''
  )
  const [team, setTeam] = useState(control.canonical.owner_team ?? '')
  const [lifecycle, setLifecycle] = useState(control.canonical.lifecycle)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [destination, setDestination] = useState<string | null>(null)
  const dirty =
    owner !== (baseline.owner_user_id?.toString() ?? '') ||
    team !== (baseline.owner_team ?? '') ||
    lifecycle !== baseline.lifecycle

  useEffect(() => {
    if (!dirty) return
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    const navigate = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return
      const anchor =
        event.target instanceof Element ? event.target.closest('a') : null
      if (
        !anchor ||
        anchor.target === '_blank' ||
        anchor.hasAttribute('download')
      )
        return
      const url = new URL(anchor.href, window.location.href)
      if (
        url.origin !== window.location.origin ||
        url.pathname === window.location.pathname
      )
        return
      event.preventDefault()
      event.stopPropagation()
      setDestination(url.pathname + url.search + url.hash)
    }
    window.addEventListener('beforeunload', beforeUnload)
    document.addEventListener('click', navigate, true)
    return () => {
      window.removeEventListener('beforeunload', beforeUnload)
      document.removeEventListener('click', navigate, true)
    }
  }, [dirty])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!dirty || busy) return
    setBusy(true)
    setError('')
    setSaved(false)
    const requestedOwner = owner ? Number(owner) : null
    try {
      const response = await fetch(`/api/compliance/controls/${control.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(requestedOwner !== null ? { owner_user_id: requestedOwner } : {}),
          owner_team: team,
          status: lifecycle,
        }),
      })
      const acknowledged = readControl(await readSectionJson(response))
      if (
        acknowledged.canonical.owner_user_id !== requestedOwner ||
        acknowledged.canonical.lifecycle !== lifecycle ||
        (acknowledged.canonical.owner_team ?? '') !== team.trim()
      )
        throw new Error('Unconfirmed save')
      setBaseline(acknowledged.canonical)
      setTeam(acknowledged.canonical.owner_team ?? '')
      setSaved(true)
    } catch {
      setError(
        'Changes could not be saved. Your edits are kept. Refresh the control if someone else changed it, then try again.'
      )
    } finally {
      setBusy(false)
    }
  }
  const selectedKnown = members.some(
    (member) => String(member.user_id) === owner
  )
  return (
    <Card className="p-4">
      <form
        onSubmit={(event) => void save(event)}
        className="space-y-4"
        aria-label="Control ownership and lifecycle"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1 text-tc-label text-tc-text">
            Owner
            <select
              className={fieldClass}
              value={owner}
              disabled={!membersReady || busy}
              onChange={(event) => {
                setOwner(event.target.value)
                setSaved(false)
              }}
            >
              <option value="" disabled={baseline.owner_user_id !== null}>
                Unassigned
              </option>
              {owner && !selectedKnown ? (
                <option value={owner}>Assigned member</option>
              ) : null}
              {members
                .filter(
                  (member) =>
                    !member.suspended || String(member.user_id) === owner
                )
                .map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.display_name || member.email}
                    {member.suspended ? ' (suspended)' : ''}
                  </option>
                ))}
            </select>
          </label>
          <label className="space-y-1 text-tc-label text-tc-text">
            Owner team
            <input
              className={fieldClass}
              value={team}
              maxLength={120}
              disabled={busy}
              onChange={(event) => {
                setTeam(event.target.value)
                setSaved(false)
              }}
            />
          </label>
          <label className="space-y-1 text-tc-label text-tc-text">
            Lifecycle
            <select
              className={fieldClass}
              value={lifecycle}
              disabled={busy}
              onChange={(event) => {
                setLifecycle(event.target.value as typeof lifecycle)
                setSaved(false)
              }}
            >
              {Object.entries(lifecycleLabels).map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-tc-label text-tc-muted">
          Verification requires approved, current evidence. The server checks
          this when you save.
        </p>
        {dirty ? (
          <p role="status" className="font-medium text-tc-text">
            Unsaved changes
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-tc-text">
            {error}
          </p>
        ) : null}
        {saved && !dirty ? (
          <p role="status" className="text-tc-text">
            Changes saved
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={!dirty || busy}>
            {busy ? 'Saving changes' : 'Save changes'}
          </Button>
          <Button
            variant="secondary"
            type="button"
            disabled={!dirty || busy}
            onClick={() => {
              setOwner(baseline.owner_user_id?.toString() ?? '')
              setTeam(baseline.owner_team ?? '')
              setLifecycle(baseline.lifecycle)
              setError('')
              setSaved(false)
            }}
          >
            Reset changes
          </Button>
        </div>
      </form>
      <ConfirmDialog
        open={destination !== null}
        title="Discard unsaved changes?"
        description="Your changes have not been saved. You can stay here to finish editing."
        confirmLabel="Discard changes"
        busy={busy}
        onClose={() => setDestination(null)}
        onConfirm={() => {
          if (destination) router.push(destination)
          setDestination(null)
        }}
      />
    </Card>
  )
}

function EvidenceReview({
  controlId,
  initial,
}: {
  controlId: string
  initial: EvidenceLink
}) {
  const [link, setLink] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  async function review() {
    if (busy) return
    setBusy(true)
    setError('')
    setSaved(false)
    try {
      const body = await readSectionJson(
        await fetch(
          `/api/compliance/controls/${controlId}/evidence/${link.id}`,
          {
            method: 'PATCH',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ verified: !link.verified }),
          }
        )
      )
      const acknowledged = readEvidence([body])[0]
      if (acknowledged.verified === link.verified)
        throw new Error('Unconfirmed review')
      // Review responses do not re-evaluate expiry metadata; retain the read snapshot.
      setLink({ ...link, verified: acknowledged.verified })
      setSaved(true)
    } catch {
      setError(
        'Evidence review could not be saved. Its verification status is unchanged. Try again.'
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="space-y-3 p-4">
      <h3 className="break-words font-semibold text-tc-text">
        {link.evidence.title || 'Untitled evidence'}
      </h3>
      <dl className="grid gap-2 text-tc-label sm:grid-cols-2">
        <div>
          <dt className="text-tc-muted">Review</dt>
          <dd className="text-tc-text">
            {link.verified ? 'Verified link' : 'Unverified link'}
          </dd>
        </div>
        <div>
          <dt className="text-tc-muted">Freshness</dt>
          <dd className="text-tc-text">
            {link.expired
              ? 'Expired'
              : link.stale
                ? 'Needs refresh'
                : 'Current according to the latest check'}
          </dd>
        </div>
      </dl>
      <Button variant="secondary" disabled={busy} onClick={() => void review()}>
        {busy
          ? 'Saving review'
          : link.verified
            ? 'Mark unverified'
            : 'Verify evidence link'}
      </Button>
      {error ? (
        <p role="alert" className="text-tc-text">
          {error}
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="text-tc-text">
          Evidence review saved
        </p>
      ) : null}
    </Card>
  )
}
