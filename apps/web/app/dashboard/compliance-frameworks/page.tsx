'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button, Card } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'
import {
  catalogStatusLabel,
  catalogDisplayState,
  enablementSucceeded,
  isProductionCatalogEnabled,
  parseCatalogList,
  parseEnableError,
  type FrameworkCatalogItem,
} from '@/lib/frameworkCatalog'

type Banner = { text: string; partial: boolean }

export default function ComplianceFrameworksPage() {
  const { permissions } = useAuth()
  const [items, setItems] = useState<FrameworkCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await fetch('/api/compliance/frameworks', { credentials: 'include' })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        const parsed = parseEnableError(body)
        setLoadError(parsed.message || 'Framework catalogs could not be loaded.')
        setItems([])
        return
      }
      const rows = parseCatalogList(body)
      setItems(rows)
    } catch {
      setLoadError('Framework catalogs could not be loaded.')
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const onEnable = async (item: FrameworkCatalogItem) => {
    const key = item.catalog_key || `row-${item.id ?? item.name}`
    setBusyKey(key)
    setBanner(null)
    try {
      const res = await fetch('/api/compliance/frameworks/enable', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: item.catalog_key || item.name,
          version: item.version || undefined,
        }),
      })
      const body = await res.json().catch(() => null)
      const parsed = parseEnableError(body)
      if (enablementSucceeded(res.status, body)) {
        setBanner({ text: 'Enablement did not meet the rights gate and was not applied.', partial: false })
      } else {
        setBanner({
          text: parsed.message,
          partial: Boolean(parsed.contract?.partial_failure),
        })
      }
      await load()
    } catch {
      setBanner({ text: 'Framework enablement was refused.', partial: false })
    } finally {
      setBusyKey(null)
    }
  }

  const enabledCount = items.filter((item) => isProductionCatalogEnabled(item)).length

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-[var(--tc-text)]">Framework catalogs</h1>
        <p className="text-sm text-[var(--tc-muted)]">
          Every advertised framework is blocked until content rights are decided in TC-01-007. No control text is
          loaded. Synthetic dev catalogs stay labelled dev/test only and are not production catalogs.
        </p>
      </header>

      {banner && (
        <div role="alert" className="rounded-xl border border-[var(--tc-border)] bg-white/5 px-4 py-3 text-sm text-[var(--tc-text)]">
          <p>{banner.text}</p>
          {banner.partial && <p className="mt-1 text-[var(--tc-muted)]">Partial failure: the catalog stays blocked.</p>}
        </div>
      )}

      {loadError && (
        <Card className="p-4">
          <p role="alert" className="text-sm text-[var(--tc-text)]">{loadError}</p>
          <Button type="button" variant="secondary" size="sm" className="mt-3" onClick={() => void load()}>
            Retry
          </Button>
        </Card>
      )}

      {loading && !loadError && <p className="text-sm text-[var(--tc-muted)]">Loading framework catalogs…</p>}

      {!loading && !loadError && (
        <Card className="overflow-x-auto p-4">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">Advertised and dev framework catalogs and their enablement state</caption>
            <thead>
              <tr className="border-b border-[var(--tc-border)] text-[var(--tc-muted)]">
                <th scope="col" className="py-2 pr-4 font-medium">Framework</th>
                <th scope="col" className="py-2 pr-4 font-medium">Version</th>
                <th scope="col" className="py-2 pr-4 font-medium">Rights</th>
                <th scope="col" className="py-2 pr-4 font-medium">State</th>
                <th scope="col" className="py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const state = catalogDisplayState(item)
                const key = `${item.catalog_key || 'row'}-${item.id ?? item.name}`
                const production = isProductionCatalogEnabled(item)
                return (
                  <tr key={key} className="border-b border-white/5 align-top">
                    <th scope="row" className="py-3 pr-4 font-medium text-[var(--tc-text)]">
                      {item.name}
                      {item.catalog_key && (
                        <span className="mt-0.5 block text-xs font-normal text-[var(--tc-muted)]">{item.catalog_key}</span>
                      )}
                    </th>
                    <td className="py-3 pr-4 text-[var(--tc-text)]">
                      {item.version || '—'}
                      <span className="mt-0.5 block text-xs text-[var(--tc-muted)]">
                        {item.content_version ? `Licensed content ${item.content_version}` : 'No licensed content version'}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-[var(--tc-text)]">{item.rights_status || 'unknown'}</td>
                    <td className="py-3 pr-4 text-[var(--tc-text)]">
                      <span>{catalogStatusLabel(item)}</span>
                      {state === 'blocked_pending_rights' && (
                        <span className="mt-0.5 block text-xs text-[var(--tc-muted)]">{item.blocked_reason}</span>
                      )}
                    </td>
                    <td className="py-3">
                      {permissions.can_admin ? (
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          disabled={production}
                          loading={busyKey === (item.catalog_key || `row-${item.id ?? item.name}`)}
                          onClick={() => void onEnable(item)}
                        >
                          {production ? 'Enabled' : 'Enable'}
                        </Button>
                      ) : (
                        <span className="text-xs text-[var(--tc-muted)]">Admin permission required to request enablement</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {items.length === 0 && <p className="pt-4 text-sm text-[var(--tc-muted)]">No framework catalogs were returned.</p>}
          <p className="pt-4 text-xs text-[var(--tc-muted)]">
            Production catalogs enabled: {enabledCount}. Blocked and dev/test rows are not production catalogs.
          </p>
        </Card>
      )}
    </div>
  )
}
