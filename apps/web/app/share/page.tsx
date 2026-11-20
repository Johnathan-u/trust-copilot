'use client'

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useKeyedGeneration } from '@/components/ui/useKeyedGeneration'

const INVALID_LINK = 'This link is invalid or has expired.'

type ShownArticle = { id: number; title: string; content: string }
type ShownAnswer = { id: number; text: string }
type ShareView = {
  name: string
  articles: ShownArticle[]
  answers: ShownAnswer[]
  documents: number[]
}
type Phase =
  | { kind: 'loading' }
  | { kind: 'denied'; reason: string }
  | { kind: 'error' }
  | { kind: 'ready'; view: ShareView }

function phaseForToken(token: string): Phase {
  if (!token) return { kind: 'denied', reason: INVALID_LINK }
  return { kind: 'loading' }
}

function idList(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  const ids: number[] = []
  for (const item of value) {
    if (typeof item !== 'number' || !Number.isInteger(item) || item < 1)
      continue
    ids.push(item)
  }
  return ids
}

function spaceName(space: unknown): string {
  if (!space || typeof space !== 'object') return 'Shared space'
  const name = (space as { name?: unknown }).name
  return typeof name === 'string' && name.trim() ? name : 'Shared space'
}

function parseAccess(body: unknown):
  | {
      ok: true
      name: string
      articleIds: number[]
      answerIds: number[]
      documentIds: number[]
    }
  | { ok: false; reason: string } {
  if (!body || typeof body !== 'object')
    return { ok: false, reason: INVALID_LINK }
  const row = body as Record<string, unknown>
  if (row.valid !== true) {
    const reason = row.reason
    return {
      ok: false,
      reason:
        typeof reason === 'string' && reason.trim() ? reason : INVALID_LINK,
    }
  }
  return {
    ok: true,
    name: spaceName(row.space),
    articleIds: idList(row.article_ids),
    answerIds: idList(row.answer_ids),
    documentIds: idList(row.document_ids),
  }
}

function tokenQuery(token: string): string {
  return new URLSearchParams({ token }).toString()
}

async function loadArticle(
  token: string,
  id: number
): Promise<ShownArticle | null> {
  try {
    const response = await fetch(
      `/api/shareable-spaces/access/articles/${id}?${tokenQuery(token)}`
    )
    if (!response.ok) return null
    const body: unknown = await response.json()
    if (!body || typeof body !== 'object') return null
    const row = body as Record<string, unknown>
    if (
      row.id !== id ||
      typeof row.title !== 'string' ||
      typeof row.content !== 'string'
    ) {
      return null
    }
    return { id, title: row.title, content: row.content }
  } catch {
    return null
  }
}

async function loadAnswer(
  token: string,
  id: number
): Promise<ShownAnswer | null> {
  try {
    const response = await fetch(
      `/api/shareable-spaces/access/answers/${id}?${tokenQuery(token)}`
    )
    if (!response.ok) return null
    const body: unknown = await response.json()
    if (!body || typeof body !== 'object') return null
    const row = body as Record<string, unknown>
    if (row.id !== id || typeof row.text !== 'string') return null
    return { id, text: row.text }
  } catch {
    return null
  }
}

export default function SharePage() {
  return (
    <Suspense
      fallback={
        <Shell>
          <p role="status">Loading shared space…</p>
        </Shell>
      }
    >
      <ShareContent />
    </Suspense>
  )
}

function ShareContent() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token')?.trim() ?? ''
  const [phase, setPhase] = useState<Phase>(() => phaseForToken(token))
  const [attempt, setAttempt] = useState(0)
  const tokenKey = useKeyedGeneration(token, { runOnMount: false })
  if (tokenKey.changed) {
    setPhase(phaseForToken(token))
  }

  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetch(`/api/shareable-spaces/access?${tokenQuery(token)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('http')
        return response.json() as Promise<unknown>
      })
      .then(async (body) => {
        const parsed = parseAccess(body)
        if (!parsed.ok) {
          if (!cancelled) setPhase({ kind: 'denied', reason: parsed.reason })
          return
        }
        const articles = (
          await Promise.all(
            parsed.articleIds.map((id) => loadArticle(token, id))
          )
        ).filter((item): item is ShownArticle => item != null)
        const answers = (
          await Promise.all(parsed.answerIds.map((id) => loadAnswer(token, id)))
        ).filter((item): item is ShownAnswer => item != null)
        if (cancelled) return
        setPhase({
          kind: 'ready',
          view: {
            name: parsed.name,
            articles,
            answers,
            documents: parsed.documentIds,
          },
        })
      })
      .catch(() => {
        if (!cancelled) setPhase({ kind: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [token, attempt])

  const retry = () => {
    setPhase({ kind: 'loading' })
    setAttempt((value) => value + 1)
  }

  if (phase.kind === 'loading') {
    return (
      <Shell>
        <p role="status">Loading shared space…</p>
      </Shell>
    )
  }

  if (phase.kind === 'denied') {
    return (
      <Shell>
        <h1 className="text-tc-title font-semibold text-tc-text">
          This link is not available
        </h1>
        <p className="text-tc-label text-tc-muted">{phase.reason}</p>
      </Shell>
    )
  }

  if (phase.kind === 'error') {
    return (
      <Shell>
        <h1 className="text-tc-title font-semibold text-tc-text">
          Something went wrong
        </h1>
        <p className="text-tc-label text-tc-muted">
          The shared space could not be loaded.
        </p>
        <button
          type="button"
          className="text-tc-label font-medium text-tc-text underline"
          onClick={retry}
        >
          Try again
        </button>
      </Shell>
    )
  }

  const { view } = phase
  return (
    <Shell>
      <h1 className="text-tc-title font-semibold text-tc-text">{view.name}</h1>
      <AssetSection title="Articles" empty={view.articles.length === 0}>
        <ul className="flex flex-col gap-tc-4">
          {view.articles.map((article) => (
            <li key={article.id}>
              <h3 className="text-tc-body font-medium text-tc-text">
                {article.title}
              </h3>
              <p className="mt-tc-1 whitespace-pre-wrap text-tc-label text-tc-text">
                {article.content}
              </p>
            </li>
          ))}
        </ul>
      </AssetSection>
      <AssetSection title="Answers" empty={view.answers.length === 0}>
        <ul className="flex flex-col gap-tc-3">
          {view.answers.map((answer) => (
            <li key={answer.id} className="text-tc-label text-tc-text">
              {answer.text}
            </li>
          ))}
        </ul>
      </AssetSection>
      <AssetSection title="Documents" empty={view.documents.length === 0}>
        <ul className="flex flex-col gap-tc-2">
          {view.documents.map((id) => (
            <li key={id}>
              <a
                className="text-tc-label font-medium text-tc-text underline"
                href={`/api/shareable-spaces/access/documents/${id}/content?${tokenQuery(token)}`}
                rel="nofollow"
                referrerPolicy="no-referrer"
              >
                Download document {id}
              </a>
            </li>
          ))}
        </ul>
      </AssetSection>
    </Shell>
  )
}

function AssetSection({
  title,
  empty,
  children,
}: {
  title: string
  empty: boolean
  children: React.ReactNode
}) {
  return (
    <section
      className="flex flex-col gap-tc-2"
      aria-labelledby={`share-${title}`}
    >
      <h2
        id={`share-${title}`}
        className="text-tc-body font-semibold text-tc-text"
      >
        {title}
      </h2>
      {empty ? (
        <p className="text-tc-label text-tc-muted">None listed.</p>
      ) : (
        children
      )}
    </section>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-tc-bg px-tc-4 py-tc-8">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-tc-4">
        {children}
      </div>
    </main>
  )
}
