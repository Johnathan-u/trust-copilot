'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button, Card, EmptyState, TableSkeleton, Toast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

type ExportRecord = {
  id: number
  questionnaire_id: number
  filename: string
  status: string
  created_at: string | null
}

export default function ExportsPage() {
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canExport = permissions.can_export
  const [records, setRecords] = useState<ExportRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [errorToast, setErrorToast] = useState<string | null>(null)

  useEffect(() => {
    if (workspaceId == null) {
      setLoading(false)
      return
    }
    setLoading(true)
    fetch(`/api/exports/records?workspace_id=${workspaceId}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then(setRecords)
      .catch(() => setRecords([]))
      .finally(() => setLoading(false))
  }, [workspaceId])

  const handleDownload = async (recordId: number, filename: string) => {
    if (workspaceId == null) return
    try {
      const r = await fetch(`/api/exports/records/${recordId}/download?workspace_id=${workspaceId}`, { credentials: 'include' })
      if (!r.ok) {
        const data = await r.json().catch(() => ({}))
        setErrorToast((data?.detail as string) || 'Download failed')
        setTimeout(() => setErrorToast(null), 5000)
        return
      }
      const blob = await r.blob()
      const disposition = r.headers.get('Content-Disposition')
      const match = disposition?.match(/filename\*?=(?:UTF-8'')?([^;]+)/)
      let name = filename || 'export.xlsx'
      if (match) {
        try {
          name = decodeURIComponent(match[1].trim().replace(/^["']|["']$/g, ''))
        } catch {
          name = filename || 'export.xlsx'
        }
      }
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      setErrorToast('Download failed. Try again.')
      setTimeout(() => setErrorToast(null), 5000)
    }
  }

  return (
    <div className="min-w-0">
      <h1 className="mb-6 text-2xl font-bold text-[var(--tc-text)]">Exports</h1>
      <Card>
        {loading ? (
          <TableSkeleton rows={4} cols={4} />
        ) : records.length === 0 ? (
          <EmptyState
            title="No exports yet"
            description="Generate answers on a questionnaire review page, then export to XLSX or DOCX."
            action={
              <Link href="/dashboard/questionnaires">
                <Button variant="secondary">Go to questionnaires</Button>
              </Link>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--tc-border-strong)] text-left" style={{ background: 'var(--tc-panel-2)' }}>
                  <th className="p-3 text-[var(--tc-muted)]">Filename</th>
                  <th className="p-3 text-[var(--tc-muted)]">Status</th>
                  <th className="p-3 text-[var(--tc-muted)]">Created</th>
                  <th className="p-3 text-[var(--tc-muted)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id} className="border-t border-[var(--tc-border)]">
                    <td className="p-3 text-[var(--tc-text)]">{r.filename}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${r.status === 'completed' ? 'bg-green-500/20 text-green-400' : 'bg-white/10 text-[var(--tc-muted)]'}`}>
                        {r.status}
                      </span>
                    </td>
                    <td className="p-3 text-[var(--tc-muted)]">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                    <td className="p-3">
                      <div className="flex gap-2">
                        <Button size="sm" variant="ghost" onClick={() => handleDownload(r.id, r.filename)} disabled={r.status !== 'completed' || !canExport}>
                          Download
                        </Button>
                        <Link href={`/dashboard/review/${r.questionnaire_id}`}>
                          <Button size="sm" variant="ghost">View review</Button>
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {errorToast && (
        <Toast title="Error" message={errorToast} type="error" onDismiss={() => setErrorToast(null)} />
      )}
    </div>
  )
}
