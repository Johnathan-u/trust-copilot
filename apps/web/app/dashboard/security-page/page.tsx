'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Button, Card } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { presentClaims, presentSecurityPage } from '@/lib/securityPage.mjs'

type PageView = ReturnType<typeof presentSecurityPage>
type ClaimRow = ReturnType<typeof presentClaims>['rows'][number]
type Draft = {
  status: 'claimed' | 'not_claimed'
  statement: string
  value: string
  evidence: string
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const value = (body as { detail?: unknown }).detail
    if (typeof value === 'string' && value) return value
  }
  return fallback
}

async function readJson(response: Response): Promise<unknown> {
  return response.json().catch(() => null)
}

function draftFor(row: ClaimRow): Draft {
  return {
    status: row.status === 'claimed' ? 'claimed' : 'not_claimed',
    statement: row.statement,
    value: row.value,
    evidence: row.evidenceItemId ? String(row.evidenceItemId) : '',
  }
}

const inputClass =
  'w-full rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)]'
const labelClass = 'mb-1 block text-xs font-medium text-[var(--tc-muted)]'

export default function SecurityPageScreen() {
  const { permissions } = useAuth()
  const canAdmin = permissions.can_admin
  const [view, setView] = useState<PageView | null>(null)
  const [rows, setRows] = useState<ClaimRow[]>([])
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  // State is only set inside promise callbacks, never synchronously, so the
  // mount effect below can start a load without cascading renders.
  const load = useCallback(
    () =>
      fetch('/api/security-page', { credentials: 'include' })
        .then(async (pageResponse) => {
          const pageBody = await readJson(pageResponse)
          if (!pageResponse.ok) {
            setView(null)
            setError(detail(pageBody, 'The security page could not be loaded.'))
            return
          }
          const next = presentSecurityPage(pageBody)
          setView(next)
          setError(next.state === 'ready' ? null : next.reason)
          if (!canAdmin) return
          const claimsResponse = await fetch('/api/security-page/claims', {
            credentials: 'include',
          })
          const claimsBody = await readJson(claimsResponse)
          const claims = claimsResponse.ok ? presentClaims(claimsBody) : null
          if (!claims || claims.state !== 'ready') {
            setError(
              claims?.reason ||
                detail(claimsBody, 'The claim editor could not be loaded.')
            )
          }
          const nextRows = claims && claims.state === 'ready' ? claims.rows : []
          setRows(nextRows)
          setDrafts(
            Object.fromEntries(nextRows.map((row) => [row.key, draftFor(row)]))
          )
        })
        .catch(() => {
          setError('Network error loading the security page.')
        })
        .finally(() => {
          setLoading(false)
        }),
    [canAdmin]
  )

  useEffect(() => {
    void load()
  }, [load])

  const update = (key: string, patch: Partial<Draft>) =>
    setDrafts((current) => ({
      ...current,
      [key]: { ...current[key], ...patch },
    }))

  const save = async (row: ClaimRow) => {
    const draft = drafts[row.key]
    if (!draft) return
    setSaving(row.key)
    setMessage(null)
    setError(null)
    const evidenceText = draft.evidence.trim()
    if (evidenceText && !/^\d+$/.test(evidenceText)) {
      setSaving(null)
      setError('Enter the evidence item ID as a whole number.')
      return
    }
    const evidence = evidenceText ? Number(evidenceText) : NaN
    try {
      const response = await fetch(
        `/api/security-page/claims/${encodeURIComponent(row.key)}`,
        {
          method: 'PUT',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            status: draft.status,
            statement: draft.statement.trim() || null,
            value: draft.value.trim() || null,
            evidence_item_id:
              Number.isInteger(evidence) && evidence > 0 ? evidence : null,
            expected_revision: row.revision,
          }),
        }
      )
      const result = await readJson(response)
      if (!response.ok) {
        setError(detail(result, 'The claim could not be saved.'))
        return
      }
      setMessage(`${row.name} saved.`)
      await load()
    } catch {
      setError('Network error saving the claim.')
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="max-w-4xl">
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="text-sm text-[var(--tc-muted)] hover:text-[var(--tc-text)]"
        >
          ← Dashboard
        </Link>
      </div>
      <h1 className="mb-1 text-2xl font-bold text-[var(--tc-text)]">
        Public security page
      </h1>
      <p className="mb-6 max-w-2xl text-sm text-[var(--tc-muted)]">
        {view?.notice ||
          'Only claims approved by an owner and backed by approved evidence are shown as attested.'}
      </p>

      {error && (
        <p role="alert" className="mb-4 text-sm text-[var(--tc-danger)]">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="mb-4 text-sm text-[var(--tc-text)]">
          {message}
        </p>
      )}
      {loading && (
        <p className="text-sm text-[var(--tc-muted)]">Loading security page…</p>
      )}

      {view && view.state === 'ready' && (
        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="mb-3 text-lg font-semibold text-[var(--tc-text)]">
              Certifications
            </h2>
            <ul className="space-y-3">
              {view.certifications.map((item) => (
                <li key={item.name} className="flex items-start gap-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      item.attested
                        ? 'bg-[var(--tc-success-surface)] text-[var(--tc-success)]'
                        : 'bg-white/5 text-[var(--tc-muted)]'
                    }`}
                  >
                    {item.label}
                  </span>
                  <div>
                    <p className="text-sm font-medium text-[var(--tc-text)]">
                      {item.name}
                    </p>
                    <p className="text-sm text-[var(--tc-muted)]">
                      {item.description}
                    </p>
                    {item.proofTitle && (
                      <p className="text-xs text-[var(--tc-muted)]">
                        Proof: {item.proofTitle}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 text-lg font-semibold text-[var(--tc-text)]">
              Infrastructure
            </h2>
            <ul className="list-disc space-y-1 pl-5 text-sm text-[var(--tc-text)]">
              {view.highlights.map((line, index) => (
                <li key={`${index}-${line}`}>{line}</li>
              ))}
            </ul>
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 text-lg font-semibold text-[var(--tc-text)]">
              Contact
            </h2>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-[var(--tc-muted)]">Security contact</dt>
              <dd className="text-[var(--tc-text)]">
                {view.contact.securityEmail ?? 'Not approved yet'}
              </dd>
              <dt className="text-[var(--tc-muted)]">
                Data processing agreement
              </dt>
              <dd className="text-[var(--tc-text)]">
                {view.contact.dpaAvailable ? 'Available' : 'Not published'}
              </dd>
              <dt className="text-[var(--tc-muted)]">Subprocessor list</dt>
              <dd className="text-[var(--tc-text)]">
                {view.contact.subprocessorListAvailable
                  ? 'Available'
                  : 'Not published'}
              </dd>
            </dl>
          </Card>

          {canAdmin && rows.length > 0 && (
            <Card className="p-5">
              <h2 className="mb-1 text-lg font-semibold text-[var(--tc-text)]">
                Owner-approved claims
              </h2>
              <p className="mb-4 text-sm text-[var(--tc-muted)]">
                A claim appears on the public page only while its proof is an
                approved evidence item in this workspace. The security contact
                needs a valid email address instead.
              </p>
              <div className="space-y-5">
                {rows.map((row) => {
                  const draft = drafts[row.key] ?? draftFor(row)
                  const id = `claim-${row.key}`
                  return (
                    <form
                      key={row.key}
                      className="rounded-lg border border-[var(--tc-border)] p-4"
                      onSubmit={(event) => {
                        event.preventDefault()
                        void save(row)
                      }}
                    >
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-[var(--tc-text)]">
                          {row.name}
                        </p>
                        <p className="text-xs text-[var(--tc-muted)]">
                          {row.reasonLabel} · revision {row.revision}
                        </p>
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                          <label
                            htmlFor={`${id}-status`}
                            className={labelClass}
                          >
                            Decision
                          </label>
                          <select
                            id={`${id}-status`}
                            value={draft.status}
                            onChange={(event) =>
                              update(row.key, {
                                status:
                                  event.target.value === 'claimed'
                                    ? 'claimed'
                                    : 'not_claimed',
                              })
                            }
                            className={inputClass}
                          >
                            <option value="not_claimed">Not claimed</option>
                            <option value="claimed">Claimed</option>
                          </select>
                        </div>
                        {row.proofRequired ? (
                          <div>
                            <label
                              htmlFor={`${id}-evidence`}
                              className={labelClass}
                            >
                              Proof (approved evidence item ID)
                            </label>
                            <input
                              id={`${id}-evidence`}
                              inputMode="numeric"
                              value={draft.evidence}
                              onChange={(event) =>
                                update(row.key, {
                                  evidence: event.target.value,
                                })
                              }
                              className={inputClass}
                            />
                          </div>
                        ) : (
                          <div>
                            <label
                              htmlFor={`${id}-value`}
                              className={labelClass}
                            >
                              Email address
                            </label>
                            <input
                              id={`${id}-value`}
                              type="email"
                              value={draft.value}
                              onChange={(event) =>
                                update(row.key, { value: event.target.value })
                              }
                              className={inputClass}
                            />
                          </div>
                        )}
                        {row.proofRequired && (
                          <div className="sm:col-span-2">
                            <label
                              htmlFor={`${id}-statement`}
                              className={labelClass}
                            >
                              Public statement (optional)
                            </label>
                            <input
                              id={`${id}-statement`}
                              maxLength={500}
                              value={draft.statement}
                              onChange={(event) =>
                                update(row.key, {
                                  statement: event.target.value,
                                })
                              }
                              className={inputClass}
                            />
                          </div>
                        )}
                      </div>
                      <div className="mt-3">
                        <Button
                          type="submit"
                          size="sm"
                          loading={saving === row.key}
                          disabled={saving !== null}
                        >
                          Save decision
                        </Button>
                      </div>
                    </form>
                  )
                })}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}
