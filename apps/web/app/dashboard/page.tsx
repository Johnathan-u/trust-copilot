'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, Button, Modal, Toast } from '@/components/ui'
import { useAuth } from '@/contexts/AuthContext'

type DashboardCard = {
  id?: number
  title: string
  description: string | null
  icon: string
  target_route: string
  sort_order?: number
  is_enabled?: boolean
  visibility_scope?: string
  size?: string
  is_builtin?: boolean
}

type AllowedMeta = {
  routes: string[]
  icons: string[]
  sizes: string[]
  visibility_scopes: string[]
}

const ICON_MAP: Record<string, string> = {
  document: '📄', questionnaire: '📋', export: '⬇', trust: '🛡',
  request: '📨', vendor: '📤', control: '🔒', compliance: '⚠',
  mapping: '🔗', audit: '📜', members: '👥', notification: '🔔',
  slack: '💬', gmail: '📧', settings: '⚙', security: '🔐',
  shield: '🛡', chart: '📊', star: '⭐', folder: '📁',
  link: '🔗', globe: '🌐', lock: '🔒', check: '✅', alert: '🚨',
}

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard/documents': 'Documents',
  '/dashboard/questionnaires': 'Questionnaires',
  '/dashboard/review': 'Review',
  '/dashboard/exports': 'Exports',
  '/dashboard/trust-center': 'Trust Center',
  '/dashboard/compliance-gaps': 'Coverage',
  '/dashboard/members': 'Members & Roles',
  '/dashboard/notifications': 'Alerts',
  '/dashboard/slack': 'Slack',
  '/dashboard/gmail': 'Gmail',
  '/dashboard/settings': 'Settings',
  '/dashboard/security': 'Account Security',
  '/dashboard/audit': 'Activity',
  '/dashboard/ai-governance': 'AI Insights',
}

const SIZE_CLASSES: Record<string, string> = {
  small: 'col-span-1',
  medium: 'col-span-1',
  large: 'md:col-span-2',
}

export default function DashboardPage() {
  const { permissions } = useAuth()
  const isAdmin = permissions.can_admin

  const [cards, setCards] = useState<DashboardCard[]>([])
  const [hasCustom, setHasCustom] = useState(false)
  const [loading, setLoading] = useState(true)

  const [showCustomize, setShowCustomize] = useState(false)
  const [editCard, setEditCard] = useState<DashboardCard | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const [allowedMeta, setAllowedMeta] = useState<AllowedMeta | null>(null)

  const fetchCards = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard/cards', { credentials: 'include' })
      if (res.ok) {
        const data = await res.json()
        setCards(data.cards ?? [])
        setHasCustom(data.has_custom ?? false)
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  const fetchMeta = useCallback(async () => {
    try {
      const res = await fetch('/api/dashboard/cards/allowed-routes', { credentials: 'include' })
      if (res.ok) setAllowedMeta(await res.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchCards() }, [fetchCards])
  useEffect(() => { if (isAdmin) fetchMeta() }, [isAdmin, fetchMeta])

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message })
    setTimeout(() => setToast(null), 3000)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this dashboard card?')) return
    try {
      const res = await fetch(`/api/dashboard/cards/${id}`, { method: 'DELETE', credentials: 'include' })
      if (res.ok) { showToast('success', 'Card deleted'); fetchCards() }
      else showToast('error', 'Failed to delete card')
    } catch { showToast('error', 'Failed to delete card') }
  }

  const customCards = cards.filter(c => !c.is_builtin && c.id != null)

  const handleMoveUp = async (customIdx: number) => {
    if (customIdx === 0) return
    const ids = customCards.map(c => c.id!)
    ;[ids[customIdx], ids[customIdx - 1]] = [ids[customIdx - 1], ids[customIdx]]
    try {
      const res = await fetch('/api/dashboard/cards/reorder', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_ids: ids }),
      })
      if (res.ok) fetchCards()
    } catch { /* ignore */ }
  }

  const handleMoveDown = async (customIdx: number) => {
    if (customIdx >= customCards.length - 1) return
    const ids = customCards.map(c => c.id!)
    ;[ids[customIdx], ids[customIdx + 1]] = [ids[customIdx + 1], ids[customIdx]]
    try {
      const res = await fetch('/api/dashboard/cards/reorder', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_ids: ids }),
      })
      if (res.ok) fetchCards()
    } catch { /* ignore */ }
  }

  if (loading) {
    return (
      <div className="min-w-0 py-6 md:py-7">
        <div className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight text-[var(--tc-text)]">Dashboard</h1>
          <p className="mt-2 text-[15px] text-[var(--tc-muted)]">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-w-0 py-6 md:py-7">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-[var(--tc-text)]">Dashboard</h1>
          <p className="mt-2 text-[15px] text-[var(--tc-muted)]">
            Upload evidence and questionnaires, then generate and export answers.
          </p>
        </div>
        {isAdmin && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowCustomize(!showCustomize)}
          >
            {showCustomize ? 'Done' : '⚙ Customize'}
          </Button>
        )}
      </div>

      {/* Admin customize bar */}
      {isAdmin && showCustomize && (
        <div className="mb-6 flex items-center gap-3 rounded-2xl border border-[var(--tc-border)] p-4"
          style={{ background: 'var(--tc-panel)' }}>
          <span className="text-sm text-[var(--tc-muted)]">
            Add custom cards to your workspace dashboard. Built-in cards always remain.
          </span>
          <Button size="sm" onClick={() => { setEditCard(null); setShowAddModal(true) }}>+ Add Card</Button>
        </div>
      )}

      {/* Cards grid */}
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {cards.map((card, idx) => {
          const isBuiltin = card.is_builtin === true
          const customIdx = isBuiltin ? -1 : customCards.findIndex(c => c.id === card.id)
          return (
            <div key={card.id ?? `builtin-${idx}`} className={SIZE_CLASSES[card.size ?? 'medium'] ?? 'col-span-1'}>
              <Link href={card.target_route}>
                <Card className="group relative transition hover:border-[var(--tc-primary)]/30 cursor-pointer">
                  <div className="flex items-start gap-3">
                    <span className="text-2xl flex-shrink-0">{ICON_MAP[card.icon] ?? '◆'}</span>
                    <div className="min-w-0">
                      <h3 className="font-semibold text-[var(--tc-text)]">{card.title}</h3>
                      {card.description && (
                        <p className="mt-1 text-sm text-[var(--tc-muted)] line-clamp-2">{card.description}</p>
                      )}
                      {showCustomize && isBuiltin && (
                        <span className="mt-1 inline-block rounded bg-blue-500/20 px-1.5 py-0.5 text-[10px] font-medium text-blue-300">
                          Built-in
                        </span>
                      )}
                      {showCustomize && !isBuiltin && card.visibility_scope === 'admin' && (
                        <span className="mt-1 inline-block rounded bg-yellow-500/20 px-1.5 py-0.5 text-[10px] font-medium text-yellow-300">
                          Admin only
                        </span>
                      )}
                      {showCustomize && !isBuiltin && card.is_enabled === false && (
                        <span className="mt-1 ml-1 inline-block rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-medium text-red-300">
                          Disabled
                        </span>
                      )}
                    </div>
                  </div>
                </Card>
              </Link>
              {isAdmin && showCustomize && !isBuiltin && card.id != null && (
                <div className="mt-1 flex items-center gap-1.5 px-1">
                  <button onClick={(e) => { e.preventDefault(); handleMoveUp(customIdx) }}
                    disabled={customIdx === 0}
                    className="rounded px-1.5 py-0.5 text-xs text-[var(--tc-muted)] hover:bg-white/10 disabled:opacity-30"
                    title="Move up">↑</button>
                  <button onClick={(e) => { e.preventDefault(); handleMoveDown(customIdx) }}
                    disabled={customIdx === customCards.length - 1}
                    className="rounded px-1.5 py-0.5 text-xs text-[var(--tc-muted)] hover:bg-white/10 disabled:opacity-30"
                    title="Move down">↓</button>
                  <button onClick={(e) => { e.preventDefault(); setEditCard(card); setShowAddModal(true) }}
                    className="rounded px-1.5 py-0.5 text-xs text-[var(--tc-muted)] hover:bg-white/10"
                    title="Edit">✏️</button>
                  <button onClick={(e) => { e.preventDefault(); handleDelete(card.id!) }}
                    className="rounded px-1.5 py-0.5 text-xs text-red-400 hover:bg-red-500/10"
                    title="Delete">🗑</button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Add/Edit modal */}
      {isAdmin && (
        <CardFormModal
          isOpen={showAddModal}
          card={editCard}
          allowedMeta={allowedMeta}
          onClose={() => { setShowAddModal(false); setEditCard(null) }}
          onSaved={() => { setShowAddModal(false); setEditCard(null); fetchCards(); showToast('success', editCard ? 'Card updated' : 'Card added') }}
          onError={(msg) => showToast('error', msg)}
        />
      )}

      {toast && (
        <div className="fixed bottom-4 right-4 z-50">
          <Toast title={toast.type === 'success' ? 'Success' : 'Error'} message={toast.message} type={toast.type} onDismiss={() => setToast(null)} />
        </div>
      )}
    </div>
  )
}


function CardFormModal({ isOpen, card, allowedMeta, onClose, onSaved, onError }: {
  isOpen: boolean
  card: DashboardCard | null
  allowedMeta: AllowedMeta | null
  onClose: () => void
  onSaved: () => void
  onError: (msg: string) => void
}) {
  const isEdit = card?.id != null
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [icon, setIcon] = useState('document')
  const [targetRoute, setTargetRoute] = useState('')
  const [visibility, setVisibility] = useState('all')
  const [size, setSize] = useState('medium')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (card) {
      setTitle(card.title)
      setDescription(card.description ?? '')
      setIcon(card.icon)
      setTargetRoute(card.target_route)
      setVisibility(card.visibility_scope ?? 'all')
      setSize(card.size ?? 'medium')
      setEnabled(card.is_enabled ?? true)
    } else {
      setTitle('')
      setDescription('')
      setIcon('document')
      setTargetRoute(allowedMeta?.routes[0] ?? '/dashboard/documents')
      setVisibility('all')
      setSize('medium')
      setEnabled(true)
    }
  }, [card, allowedMeta, isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) { onError('Title is required'); return }
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim() || null,
        icon,
        target_route: targetRoute,
        visibility_scope: visibility,
        size,
        is_enabled: enabled,
      }
      const url = isEdit ? `/api/dashboard/cards/${card!.id}` : '/api/dashboard/cards'
      const method = isEdit ? 'PATCH' : 'POST'
      const res = await fetch(url, {
        method, credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) { onSaved() }
      else {
        const d = await res.json().catch(() => ({}))
        onError(d.detail ?? 'Failed to save card')
      }
    } catch { onError('Failed to save card') }
    finally { setSaving(false) }
  }

  const routes = allowedMeta?.routes ?? Object.keys(ROUTE_LABELS)
  const icons = allowedMeta?.icons ?? Object.keys(ICON_MAP)

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={isEdit ? 'Edit Card' : 'Add Card'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Title</label>
          <input value={title} onChange={e => setTitle(e.target.value)}
            className="w-full rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)]"
            maxLength={128} required />
        </div>
        <div>
          <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Description</label>
          <textarea value={description} onChange={e => setDescription(e.target.value)}
            className="w-full rounded-lg border border-[var(--tc-border)] bg-white/5 px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)] resize-none"
            rows={2} maxLength={500} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Page</label>
            <select value={targetRoute} onChange={e => setTargetRoute(e.target.value)}
              className="w-full rounded-lg border border-[var(--tc-border)] px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)]">
              {routes.map(r => (
                <option key={r} value={r}>{ROUTE_LABELS[r] ?? r}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Icon</label>
            <select value={icon} onChange={e => setIcon(e.target.value)}
              className="w-full rounded-lg border border-[var(--tc-border)] px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)]">
              {icons.map(i => (
                <option key={i} value={i}>{ICON_MAP[i] ?? '◆'} {i}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Size</label>
            <select value={size} onChange={e => setSize(e.target.value)}
              className="w-full rounded-lg border border-[var(--tc-border)] px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)]">
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--tc-muted)] mb-1">Visibility</label>
            <select value={visibility} onChange={e => setVisibility(e.target.value)}
              className="w-full rounded-lg border border-[var(--tc-border)] px-3 py-2 text-sm text-[var(--tc-text)] focus:outline-none focus:ring-1 focus:ring-[var(--tc-primary)]">
              <option value="all">Everyone</option>
              <option value="admin">Admin only</option>
            </select>
          </div>
          <div className="flex items-end pb-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
                className="rounded border-[var(--tc-border)]" />
              <span className="text-xs text-[var(--tc-text)]">Enabled</span>
            </label>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" size="sm" onClick={onClose} type="button">Cancel</Button>
          <Button size="sm" type="submit" disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Update' : 'Add Card'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
