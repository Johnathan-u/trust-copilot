'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { Button, Card, Input } from '@/components/ui'
import { MarkdownContent } from '@/components/MarkdownContent'

const ALLOWED_EXTENSIONS = '.pdf,.docx,.doc,.xlsx,.xls,.txt'

type WorkspaceInfo = {
  id: number
  name: string
  slug: string
}

type Article = {
  id: number
  slug: string
  title: string
  category?: string | null
  content?: string | null
  updated_at?: string | null
}

function formatUpdated(updated_at: string | null | undefined): string | null {
  if (!updated_at) return null
  const d = new Date(updated_at)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffDays = Math.floor(diffMs / (24 * 60 * 60 * 1000))
  if (diffDays === 0) return 'Updated today'
  if (diffDays === 1) return 'Updated yesterday'
  if (diffDays < 30) return `Updated ${diffDays} days ago`
  return `Updated ${d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })}`
}

function previewText(content: string | null | undefined, maxLen: number): string {
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

export default function WorkspaceTrustPage() {
  const params = useParams()
  const slug = typeof params.slug === 'string' ? params.slug : ''

  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [loading, setLoading] = useState(true)

  const [articles, setArticles] = useState<Article[]>([])
  const [selected, setSelected] = useState<{ title: string; content: string } | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ requester_email: '', requester_name: '', subject: '', message: '' })
  const [formSuccess, setFormSuccess] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formSubmitting, setFormSubmitting] = useState(false)
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!slug) return
    setLoading(true)
    fetch(`/api/workspaces/by-slug/${encodeURIComponent(slug)}`)
      .then((r) => {
        if (!r.ok) { setNotFound(true); setLoading(false); return null }
        return r.json()
      })
      .then((data) => {
        if (!data) return
        setWorkspace(data)
        setLoading(false)
        fetch(`/api/trust-articles?workspace_id=${data.id}&published_only=true`)
          .then((r) => (r.ok ? r.json() : []))
          .then(setArticles)
      })
      .catch(() => { setNotFound(true); setLoading(false) })
  }, [slug])

  const openArticle = (id: number) => {
    if (!workspace) return
    fetch(`/api/trust-articles/${id}?workspace_id=${workspace.id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setSelected({ title: d.title, content: d.content || '' }))
  }

  const submitRequest = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormSubmitting(true)
    setFormSuccess(false)
    setFormError(null)
    try {
      const body = new FormData()
      body.append('requester_email', form.requester_email)
      body.append('requester_name', form.requester_name)
      body.append('subject', form.subject)
      body.append('message', form.message)
      body.append('workspace_slug', slug)
      const file = fileInputRef.current?.files?.[0]
      if (file) body.append('document', file)
      const res = await fetch('/api/trust-requests/submit', {
        method: 'POST',
        body,
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok) {
        setFormSuccess(true)
        setForm({ requester_email: '', requester_name: '', subject: '', message: '' })
        if (fileInputRef.current) fileInputRef.current.value = ''
        setSelectedFileName(null)
        setShowForm(false)
      } else {
        setFormError((data?.detail as string) || 'Submission failed. Please try again.')
      }
    } catch {
      setFormError('Submission failed. Please try again.')
    } finally {
      setFormSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-[var(--tc-muted)] border-t-[var(--tc-primary)]" />
      </div>
    )
  }

  if (notFound || !workspace) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6">
        <h1 className="text-2xl font-bold text-[var(--tc-text)]">Trust Center not found</h1>
        <p className="text-[var(--tc-muted)] text-center max-w-md">
          No workspace matches <span className="font-mono text-[var(--tc-text)]">/trust/{slug}</span>.
          Please check the link you were given.
        </p>
        <Link href="/login" className="text-sm text-[var(--tc-primary)] hover:underline">
          Sign in instead
        </Link>
      </div>
    )
  }

  const companyName = workspace.name

  return (
    <div className="relative min-h-screen">
      <header className="sticky top-0 z-10 border-b border-[var(--tc-border)] bg-[var(--tc-panel)]/95 backdrop-blur-md py-4 px-6">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--tc-primary)]/15 text-[var(--tc-primary)] font-bold text-sm">
              {companyName.charAt(0).toUpperCase()}
            </div>
            <h1 className="text-xl font-bold tracking-tight text-[var(--tc-text)]">{companyName} Trust Center</h1>
          </div>
          <Link href="/login" className="text-sm font-medium text-[var(--tc-muted)] hover:text-[var(--tc-text)] transition-colors">Sign in</Link>
        </div>
      </header>
      <main className="relative max-w-4xl mx-auto py-8 px-6">
        <p className="text-lg text-[var(--tc-text)] mb-1">
          Security and compliance information for {companyName}.
        </p>
        <p className="text-[15px] text-[var(--tc-muted)] mb-6">
          View published policies and articles, or submit a trust information request.
        </p>
        {formSuccess && (
          <div className="mb-4 rounded-xl bg-[var(--tc-success)]/10 p-3 text-sm text-[var(--tc-success)]">
            Your request has been sent to <strong>{companyName}</strong>. We&apos;ll be in touch soon.
            <span className="block mt-1 opacity-90">We typically respond within 2 business days.</span>
          </div>
        )}
        <div className="mb-8">
          <Button
            onClick={() => {
              setShowForm((prev) => !prev)
              if (!showForm) setFormError(null)
            }}
            variant={showForm ? 'ghost' : 'primary'}
            size="md"
          >
            {showForm ? 'Cancel' : `Request trust information from ${companyName}`}
          </Button>
          {showForm && (
            <>
              <p className="mt-3 text-sm text-[var(--tc-muted)]">
                Submit a trust information request to <strong>{companyName}</strong>.
              </p>
              <Card className="mt-4 p-6">
              {formError && (
                <div className="mb-4 rounded-xl bg-red-500/10 p-3 text-sm text-red-400">
                  {formError}
                </div>
              )}
              <form onSubmit={submitRequest} className="space-y-4">
                <Input
                  label="Email"
                  type="email"
                  required
                  value={form.requester_email}
                  onChange={(e) => setForm((f) => ({ ...f, requester_email: e.target.value }))}
                />
                <Input
                  label="Name"
                  value={form.requester_name}
                  onChange={(e) => setForm((f) => ({ ...f, requester_name: e.target.value }))}
                />
                <Input
                  label="Subject"
                  value={form.subject}
                  onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
                />
                <div>
                  <label className="mb-1 block text-sm font-medium text-[var(--tc-muted)]">Message</label>
                  <textarea
                    required
                    className="w-full rounded-xl border border-[var(--tc-border)] bg-white/5 px-3 py-2.5 text-[var(--tc-text)] placeholder:text-[var(--tc-muted)] focus:border-[var(--tc-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)] min-h-[100px]"
                    placeholder="Your message"
                    value={form.message}
                    onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-[var(--tc-muted)]">Upload document (optional)</label>
                  <div className="flex flex-wrap items-center gap-3">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept={ALLOWED_EXTENSIONS}
                      className="sr-only"
                      aria-label="Choose file"
                      onChange={(e) => setSelectedFileName(e.target.files?.[0]?.name ?? null)}
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      size="md"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      Choose file
                    </Button>
                    {selectedFileName && (
                      <span className="text-sm text-[var(--tc-muted)] truncate max-w-[200px]" title={selectedFileName}>
                        {selectedFileName}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-[var(--tc-muted)]">PDF, DOCX, DOC, XLSX, XLS, or TXT. Max 50MB.</p>
                </div>
                <Button type="submit" loading={formSubmitting}>
                  {formSubmitting ? 'Sending…' : `Submit to ${companyName}`}
                </Button>
              </form>
            </Card>
            </>
          )}
        </div>
        <div className="space-y-8">
          {(() => {
            const byCategory = articles.reduce<Record<string, Article[]>>((acc, a) => {
              const cat = (a.category && a.category.trim()) || 'General'
              if (!acc[cat]) acc[cat] = []
              acc[cat].push(a)
              return acc
            }, {})
            const sectionOrder = ['SOC 2', 'Data Privacy', 'Security Overview', 'General']
            const categories = Object.keys(byCategory).sort(
              (a, b) => sectionOrder.indexOf(a) - sectionOrder.indexOf(b) || a.localeCompare(b)
            )
            if (categories.length === 0 && articles.length === 0) {
              return <p className="text-[var(--tc-muted)]">No published articles yet.</p>
            }
            return categories.map((cat) => (
              <section key={cat}>
                <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--tc-muted)] mb-3">{cat}</h2>
                <div className="grid gap-3">
                  {byCategory[cat].map((a) => {
                    const teaser = previewText(a.content, 50000) || `How we approach ${a.title}.`
                    const updatedLabel = formatUpdated(a.updated_at)
                    return (
                      <Card
                        key={a.id}
                        className="group cursor-pointer transition-all duration-200 hover:border-[var(--tc-border-strong)]"
                        onClick={() => openArticle(a.id)}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="font-semibold text-[var(--tc-text)]">{a.title}</h3>
                          {updatedLabel && (
                            <span className="shrink-0 text-xs text-[var(--tc-muted)]">{updatedLabel}</span>
                          )}
                        </div>
                        <div className="mt-0 grid grid-rows-[0fr] transition-[grid-template-rows] duration-200 group-hover:grid-rows-[1fr]">
                          <div className="overflow-hidden">
                            <p className="mt-2 text-sm text-[var(--tc-muted)] whitespace-pre-wrap">{teaser}</p>
                          </div>
                        </div>
                      </Card>
                    )
                  })}
                </div>
              </section>
            ))
          })()}
        </div>
        {selected && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={() => setSelected(null)}>
            <Card className="flex max-w-2xl w-full max-h-[90vh] flex-col overflow-hidden" padding="lg" onClick={(e) => e.stopPropagation()}>
              <div className="flex justify-between items-start gap-4 shrink-0 mb-4">
                <h2 className="text-lg font-bold text-[var(--tc-text)]">{selected.title}</h2>
                <button type="button" className="shrink-0 rounded-lg p-1 text-[var(--tc-muted)] hover:text-[var(--tc-text)] hover:bg-white/5 transition-colors" onClick={() => setSelected(null)} aria-label="Close">&times;</button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto -mx-2 px-2">
                <MarkdownContent content={selected.content} className="text-[var(--tc-text)] [&_a]:text-[var(--tc-primary)] [&_a]:hover:underline" />
              </div>
            </Card>
          </div>
        )}
      </main>
    </div>
  )
}
