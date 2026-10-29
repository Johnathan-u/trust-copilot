'use client'

import Link from 'next/link'
import { useState } from 'react'
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import { presentHttpFailure } from '@/lib/api-error'
import { parseCoverageResponse } from '@/lib/coverageConsumer'
import {
  isDevTestOnly,
  isProductionCatalogEnabled,
  type FrameworkCatalogItem,
} from '@/lib/frameworkCatalog'
import { readSectionJson, sectionFailure } from '@/lib/section-load'
import {
  evaluationLabel,
  fieldClass,
  lifecycleLabels,
  linkClass,
  readControls,
  record,
  useResource,
} from './control-data'

function readCatalogs(value: unknown): FrameworkCatalogItem[] {
  if (!Array.isArray(value)) throw new Error('Invalid catalogs')
  return value.map((item) => {
    const row = record(item)
    if (
      typeof row.name !== 'string' ||
      row.contract_version !== 'framework-catalog/v1'
    )
      throw new Error('Invalid catalog')
    return row as FrameworkCatalogItem
  })
}

export default function ControlLibraryPage() {
  const auth = useAuth()
  if (!auth.permissions.can_review)
    return (
      <ErrorState
        failure={presentHttpFailure({ status: 403 })}
        onRetry={() => void auth.refresh()}
      />
    )
  return (
    <ControlLibrary
      key={`${auth.workspace?.id}:${auth.permissions.can_admin}`}
      canAdmin={auth.permissions.can_admin}
    />
  )
}

function ControlLibrary({ canAdmin }: { canAdmin: boolean }) {
  const controls = useResource('/api/compliance/controls', readControls)
  const catalogs = useResource('/api/compliance/frameworks', readCatalogs)
  const coverage = useResource(
    '/api/compliance-coverage',
    parseCoverageResponse
  )
  const [search, setSearch] = useState('')
  const [lifecycle, setLifecycle] = useState('')
  const [page, setPage] = useState(0)
  const rows = controls.result?.ok ? controls.result.data : []
  const visible = rows.filter(
    (row) =>
      `${row.name ?? ''} ${row.framework ?? ''} ${row.canonical.owner_team ?? ''}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (!lifecycle || row.canonical.lifecycle === lifecycle)
  )
  const shown = visible.slice(page * 25, (page + 1) * 25)
  const explanations = coverage.result?.ok
    ? coverage.result.data.control_coverage.explanations
    : []
  return (
    <div className="min-w-0 space-y-6 pb-8">
      <header className="space-y-2">
        <h1 className="text-tc-headline font-semibold text-tc-text">
          Control library
        </h1>
        <p className="max-w-3xl text-tc-body text-tc-muted">
          Manage control ownership and review supporting evidence. Lifecycle
          tracks your work; evidence evaluation is separate and does not
          establish certification or compliance.
        </p>
        <Link className={linkClass} href="/dashboard/compliance-frameworks">
          Framework catalogs
        </Link>
      </header>
      <section aria-labelledby="framework-heading" className="space-y-3">
        <h2
          id="framework-heading"
          className="text-tc-title font-semibold text-tc-text"
        >
          Framework availability
        </h2>
        {!catalogs.result ? (
          <LoadingState
            label="Loading frameworks"
            onRetry={catalogs.reload}
            resetKey={catalogs.attempt}
          />
        ) : !catalogs.result.ok ? (
          <ErrorState
            failure={sectionFailure(catalogs.result)}
            onRetry={catalogs.reload}
          />
        ) : catalogs.result.data.length === 0 ? (
          <p className="text-tc-muted">No framework catalogs were returned.</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {catalogs.result.data.map((item, index) => (
              <li key={item.catalog_key ?? index}>
                <FrameworkCard item={item} canAdmin={canAdmin} />
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="controls-heading" className="space-y-4">
        <h2
          id="controls-heading"
          className="text-tc-title font-semibold text-tc-text"
        >
          Workspace controls
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-tc-label text-tc-text">
            Search controls
            <input
              className={fieldClass}
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setPage(0)
              }}
            />
          </label>
          <label className="space-y-1 text-tc-label text-tc-text">
            Filter lifecycle
            <select
              className={fieldClass}
              value={lifecycle}
              onChange={(event) => {
                setLifecycle(event.target.value)
                setPage(0)
              }}
            >
              <option value="">All lifecycles</option>
              {Object.entries(lifecycleLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {coverage.result && !coverage.result.ok ? (
          <div className="rounded-tc border border-tc-border p-4">
            <p role="status" className="text-tc-text">
              Evaluation unavailable
            </p>
            <p className="text-tc-muted">
              Controls remain available. Their evidence evaluation could not be
              loaded.
            </p>
            <Button variant="secondary" onClick={coverage.reload}>
              Retry evaluation
            </Button>
          </div>
        ) : null}
        {!controls.result ? (
          <LoadingState
            label="Loading controls"
            onRetry={controls.reload}
            resetKey={controls.attempt}
          >
            <p className="text-tc-muted">Loading controls…</p>
          </LoadingState>
        ) : !controls.result.ok ? (
          <ErrorState
            failure={sectionFailure(controls.result)}
            onRetry={controls.reload}
          />
        ) : !rows.length ? (
          <EmptyState
            title="No controls yet"
            description="Controls added to this workspace will appear here. Framework availability is shown above."
          />
        ) : !visible.length ? (
          <EmptyState
            title="No matching controls"
            description="Try another search or lifecycle filter."
          />
        ) : (
          <>
            <div
              role="region"
              aria-label="Workspace control list"
              tabIndex={0}
              className="max-w-full overflow-x-auto rounded-tc border border-tc-border"
            >
              <table className="w-full min-w-[620px] text-left text-tc-label text-tc-text">
                <caption className="sr-only">
                  Control ownership, lifecycle and independent evidence
                  evaluation
                </caption>
                <thead>
                  <tr className="border-b border-tc-border bg-tc-surface-raised">
                    {[
                      'Control',
                      'Owner team',
                      'Lifecycle',
                      'Evidence evaluation',
                    ].map((label) => (
                      <th key={label} scope="col" className="p-3 font-semibold">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row) => (
                    <tr
                      key={row.id}
                      className="border-b border-tc-border align-top"
                    >
                      <th
                        scope="row"
                        className="max-w-64 break-words p-3 font-medium"
                      >
                        <Link
                          className={linkClass}
                          href={`/dashboard/controls/${row.id}`}
                        >
                          {row.name || 'Untitled control'}
                        </Link>
                        <span className="block text-tc-muted">
                          {row.framework || 'Custom control'}
                        </span>
                      </th>
                      <td className="max-w-48 break-words p-3">
                        {row.canonical.owner_team ||
                          (row.canonical.owner_user_id
                            ? 'Assigned member'
                            : 'Unassigned')}
                      </td>
                      <td className="p-3">
                        {lifecycleLabels[row.canonical.lifecycle]}
                      </td>
                      <td className="p-3">
                        {evaluationLabel(
                          explanations.find(
                            (item) => item.control_id === row.id
                          )
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-tc-label text-tc-muted">
              <p role="status">
                Showing {page * 25 + 1}–
                {Math.min((page + 1) * 25, visible.length)} of {visible.length}{' '}
                controls
              </p>
              <Button
                variant="secondary"
                disabled={page === 0}
                onClick={() => setPage((value) => value - 1)}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={(page + 1) * 25 >= visible.length}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </Button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

function FrameworkCard({
  item,
  canAdmin,
}: {
  item: FrameworkCatalogItem
  canAdmin: boolean
}) {
  const [current, setCurrent] = useState(item)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const enabled = isProductionCatalogEnabled(current)
  const eligible =
    !isDevTestOnly(current) &&
    current.production_catalog === true &&
    current.rights_status === 'cleared' &&
    current.licence_status === 'cleared' &&
    Boolean(current.content_version && current.catalog_key)
  async function enable() {
    if (!eligible || !canAdmin || busy) return
    setBusy(true)
    setMessage('')
    try {
      await readSectionJson(
        await fetch('/api/compliance/frameworks/enable', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ catalog_key: current.catalog_key }),
        })
      )
      const list = readCatalogs(
        await readSectionJson(
          await fetch('/api/compliance/frameworks', { credentials: 'include' })
        )
      )
      const acknowledged = list.find(
        (value) => value.catalog_key === current.catalog_key
      )
      if (!acknowledged || !isProductionCatalogEnabled(acknowledged))
        throw new Error('Unconfirmed')
      setCurrent(acknowledged)
      setMessage('Framework enabled')
    } catch {
      setMessage(
        'Framework activation could not be confirmed. Refresh the page before trying again.'
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="h-full space-y-2 p-4">
      <h3 className="break-words font-semibold text-tc-text">{current.name}</h3>
      <p className="text-tc-label text-tc-muted">
        {enabled
          ? 'Enabled'
          : isDevTestOnly(current)
            ? 'Test catalog — unavailable for production'
            : eligible
              ? 'Licensed content available'
              : 'Pending content licensing'}
      </p>
      {current.content_version && eligible ? (
        <p className="text-tc-caption text-tc-muted">
          Content version: {current.content_version}
        </p>
      ) : null}
      {eligible && !enabled && canAdmin ? (
        <Button disabled={busy} onClick={() => void enable()}>
          {busy ? 'Activating…' : 'Enable framework'}
        </Button>
      ) : null}
      {message ? (
        <p role="status" className="text-tc-label text-tc-text">
          {message}
        </p>
      ) : null}
    </Card>
  )
}
