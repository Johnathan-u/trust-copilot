'use client'

import { useEffect, useState } from 'react'
import { Button, Card, EmptyState, Input, Modal, Toast } from '@/components/ui'
import { ListSkeleton } from '@/components/ui/Skeleton'
import { useAuth } from '@/contexts/AuthContext'

type TrustArticle = {
  id: number
  workspace_id: number | null
  slug: string
  category: string | null
  title: string
  content: string | null
  published: number
  is_policy: boolean
  created_at: string | null
  updated_at: string | null
}

const emptyForm = { slug: '', title: '', content: '', category: '', is_policy: false }

/** Relative time for updated_at (e.g. "2 days ago"). */
function formatUpdatedAt(updated_at: string | null | undefined): string | null {
  if (!updated_at) return null
  const d = new Date(updated_at)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffDays = Math.floor(diffMs / (24 * 60 * 60 * 1000))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 30) return `${diffDays} days ago`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Plain-text preview from markdown for overview cards (no raw markdown leak). */
function previewFromMarkdown(content: string | null | undefined, maxLen: number): string {
  if (!content || !content.trim()) return ''
  const stripped = content
    .replace(/#{1,6}\s*/g, '')
    .replace(/\*\*?([^*]*)\*\*?/g, '$1')
    .replace(/__?([^_]*)__?/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
  return stripped.length <= maxLen ? stripped : stripped.slice(0, maxLen) + '…'
}

/** TC-H-F1: Section slugs for customer-style overview (match seed or similar). */
const SECTION_SLUGS: { slug: string; label: string }[] = [
  { slug: 'demo-compliance-soc2', label: 'SOC 2 Compliance' },
  { slug: 'demo-data-privacy', label: 'Data Privacy' },
  { slug: 'demo-security-overview', label: 'Security Overview' },
]

export default function TrustCenterPage() {
  const { workspace, permissions } = useAuth()
  const workspaceId = workspace?.id
  const canAdmin = permissions.can_admin
  const [articles, setArticles] = useState<TrustArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [toastType, setToastType] = useState<'success' | 'error'>('error')
  const [policies, setPolicies] = useState<TrustArticle[]>([])
  const [acknowledged, setAcknowledged] = useState<Set<number>>(new Set())
  const load = () => {
    if (workspaceId == null) { setLoading(false); return }
    if (articles.length === 0) setLoading(true)
    setRefreshing(true)
    fetch(`/api/trust-articles?workspace_id=${workspaceId}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setArticles(Array.isArray(data) ? data : []))
      .catch(() => setArticles([]))
      .finally(() => { setLoading(false); setRefreshing(false) })
  }

  useEffect(() => {
    load()
  }, [workspaceId])

  useEffect(() => {
    if (workspaceId == null) return
    fetch(`/api/trust-articles?workspace_id=${workspaceId}&policy_only=true`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setPolicies(Array.isArray(data) ? data : []))
      .catch(() => setPolicies([]))
  }, [workspaceId])

  useEffect(() => {
    fetch('/api/trust-articles/policy-acknowledgments', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : { acknowledged_article_ids: [] }))
      .then((data) => setAcknowledged(new Set((data.acknowledged_article_ids as number[]) || [])))
      .catch(() => {})
  }, [])

  const openAdd = () => {
    setEditId(null)
    setForm(emptyForm)
    setError(null)
    setFormOpen(true)
  }

  const openEdit = (a: TrustArticle) => {
    setEditId(a.id)
    setForm({ slug: a.slug, title: a.title, content: a.content ?? '', category: a.category ?? '', is_policy: a.is_policy ?? false })
    setError(null)
    setFormOpen(true)
  }

  const closeForm = () => {
    setFormOpen(false)
    setEditId(null)
    setForm(emptyForm)
    setError(null)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (workspaceId == null) return
    setSubmitting(true)
    setError(null)
    try {
      if (editId) {
        const res = await fetch(`/api/trust-articles/${editId}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            slug: form.slug,
            title: form.title,
            content: form.content,
            category: form.category.trim() || null,
            is_policy: form.is_policy,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail ?? res.statusText)
        }
      } else {
        const res = await fetch('/api/trust-articles/', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            slug: form.slug,
            title: form.title,
            content: form.content,
            category: form.category.trim() || null,
            is_policy: form.is_policy,
            workspace_id: workspaceId,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail ?? res.statusText)
        }
      }
      load()
      closeForm()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setSubmitting(false)
    }
  }

  const acknowledgePolicy = async (articleId: number) => {
    const res = await fetch(`/api/trust-articles/${articleId}/acknowledge`, { method: 'POST', credentials: 'include' })
    if (res.ok) setAcknowledged((prev) => new Set(prev).add(articleId))
    else {
      const data = await res.json().catch(() => ({}))
      setToastType('error')
      setToast((data?.detail as string) || 'Failed to acknowledge')
      setTimeout(() => setToast(null), 5000)
    }
  }

  const onDelete = async (id: number) => {
    if (!confirm('Delete this article?')) return
    try {
      const res = await fetch(`/api/trust-articles/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      if (res.ok) {
        load()
        setToast(null)
      } else {
        const data = await res.json().catch(() => ({}))
        setToastType('error')
        setToast((data?.detail as string) || 'Delete failed')
        setTimeout(() => setToast(null), 5000)
      }
    } catch {
      setToastType('error')
      setToast('Delete failed. Try again.')
      setTimeout(() => setToast(null), 5000)
    }
  }

  const workspaceSlug = workspace?.slug || ''
  const publicTrustUrl = typeof window !== 'undefined' && workspaceSlug ? `${window.location.origin}/trust/${workspaceSlug}` : ''
  const copyPublicLink = () => {
    if (!publicTrustUrl) return
    navigator.clipboard.writeText(publicTrustUrl).then(
      () => {
        setToastType('success')
        setToast('Public link copied to clipboard')
        setTimeout(() => setToast(null), 3000)
      },
      () => {
        setToastType('error')
        setToast('Could not copy')
        setTimeout(() => setToast(null), 3000)
      }
    )
  }

  return (
    <div className="min-w-0 p-7">
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-[var(--tc-text)]">Trust Center</h1>
          <p className="mt-2 text-[15px] text-[var(--tc-muted)]">
            Manage trust articles and what customers see on your public Trust page.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => window.open(publicTrustUrl || '/trust', '_blank', 'noopener,noreferrer')}
              disabled={!publicTrustUrl}
            >
              View public page
            </Button>
            <Button variant="ghost" size="sm" onClick={copyPublicLink} disabled={!publicTrustUrl}>
              Copy public link
            </Button>
          </div>
        </div>
        {canAdmin && <Button onClick={openAdd} disabled={workspaceId == null}>Add article</Button>}
      </div>

      {policies.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Policy repository</h2>
          <p className="mb-3 text-sm text-[var(--tc-muted)]">Articles marked as policy. Acknowledge to record that you have read them.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {policies.map((p) => (
              <Card key={p.id} className="flex items-center justify-between p-4">
                <span className="font-medium text-[var(--tc-text)]">{p.title}</span>
                {acknowledged.has(p.id) ? (
                  <span className="text-xs text-[var(--tc-success)]">Acknowledged</span>
                ) : (
                  <Button variant="ghost" size="sm" onClick={() => acknowledgePolicy(p.id)}>Acknowledge</Button>
                )}
              </Card>
            ))}
          </div>
        </section>
      )}

      {!loading && articles.length > 0 && (
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Overview (what customers see)</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {SECTION_SLUGS.map(({ slug, label }) => {
              const article = articles.find((a) => a.slug === slug)
              return (
                <Card key={slug} className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-semibold text-[var(--tc-text)]">{label}</h3>
                    {article && canAdmin && (
                      <Button variant="ghost" size="sm" onClick={() => openEdit(article)}>
                        Edit
                      </Button>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm text-[var(--tc-muted)]">
                    {article ? (previewFromMarkdown(article.content, 120) || 'No content') : `No article with slug "${slug}"`}
                  </p>
                  {article && formatUpdatedAt(article.updated_at) && (
                    <p className="mt-1 text-xs text-[var(--tc-muted)]">Updated {formatUpdatedAt(article.updated_at)}</p>
                  )}
                </Card>
              )
            })}
          </div>
        </section>
      )}

      <Card>
        {loading ? (
          <ListSkeleton rows={4} />
        ) : articles.length === 0 ? (
          <EmptyState
            title="No trust articles yet"
            description="Add articles to publish in your Trust Center for customers and prospects."
            action={canAdmin && <Button onClick={openAdd}>Add your first article</Button>}
          />
        ) : (
          <ul className="divide-y divide-white/10">
            {articles.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-[var(--tc-text)]">{a.title}</span>
                  <span className="text-sm text-[var(--tc-muted)]">
                    {a.slug}{a.category ? ` · ${a.category}` : ''}
                    {formatUpdatedAt(a.updated_at) && ` · Updated ${formatUpdatedAt(a.updated_at)}`}
                  </span>
                </div>
                {canAdmin && (
                  <div className="flex shrink-0 gap-2">
                    <Button variant="ghost" size="sm" onClick={() => openEdit(a)}>
                      Edit
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => onDelete(a.id)} className="text-[var(--tc-danger)] hover:opacity-90">
                      Delete
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal isOpen={formOpen} onClose={closeForm} title={editId ? 'Edit article' : 'Add article'}>
        <form onSubmit={submit} className="space-y-4">
          <Input
            label="Slug"
            placeholder="security-overview"
            value={form.slug}
            onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
            required
          />
          <Input
            label="Title"
            placeholder="Security overview"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            required
          />
          <Input
            label="Category (section)"
            placeholder="e.g. SOC 2, Data Privacy, Security Overview"
            value={form.category}
            onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
          />
          <label className="flex items-center gap-2 text-sm text-[var(--tc-text)]">
            <input type="checkbox" checked={form.is_policy} onChange={(e) => setForm((f) => ({ ...f, is_policy: e.target.checked }))} />
            Mark as policy (for policy repository)
          </label>
          <div>
            <label className="block text-sm font-medium text-[var(--tc-muted)] mb-1">Content</label>
            <textarea
              className="w-full rounded-lg border border-[var(--tc-border)] px-3 py-2 bg-transparent text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:border-[var(--tc-soft)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-soft)] min-h-[120px]"
              placeholder="Article content (Markdown supported)"
              value={form.content}
              onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
            />
          </div>
          {error && <div className="rounded-xl bg-[var(--tc-danger)]/10 p-3 text-sm text-[var(--tc-danger)]">{error}</div>}
          <div className="flex gap-2 justify-end pt-2">
            <Button type="button" variant="ghost" onClick={closeForm}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Saving...' : editId ? 'Save' : 'Create'}
            </Button>
          </div>
        </form>
      </Modal>
      {toast && (
        <Toast
          title={toastType === 'success' ? 'Copied' : 'Error'}
          message={toast}
          type={toastType}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}
