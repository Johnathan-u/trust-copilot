'use client'

import { useEffect, useRef, useState } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { Button } from '@/components/ui/Button'
import {
  deliveryLabel,
  parseTrustNote,
  parseTrustNotes,
  parseTrustRequest,
  parseTrustRequests,
  replyActions,
  TrustApiError,
  trustFailure,
  trustFetch,
  trustJson,
  type TrustNote,
  type TrustRequest,
} from '@/lib/trust-request-consumer'

const field =
  'w-full rounded-tc-sm border border-tc-border-strong bg-tc-surface p-tc-3 text-tc-text'
const panel =
  'min-w-0 space-y-tc-4 rounded-tc border border-tc-border bg-tc-surface p-tc-4'
const failure = (error: unknown) =>
  trustFailure(error instanceof TrustApiError ? error.status : 0)
function Notice({ children }: { children: string }) {
  return (
    <p
      role="alert"
      className="rounded-tc-sm border border-tc-border p-tc-3 text-tc-danger"
    >
      {children}
    </p>
  )
}
function useAlive() {
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  return alive
}
export default function TrustRequestsPage() {
  const { workspace, user, permissions, loading } = useAuth()
  if (loading) return <p role="status">Loading workspace…</p>
  if (!workspace || !user) return null
  if (!permissions.can_review)
    return (
      <section className={panel}>
        <h1 className="text-tc-h1">Review access required</h1>
        <p>
          Your current workspace permissions do not allow incoming Trust request
          review.
        </p>
      </section>
    )
  return <Inbox key={`${user.id}:${workspace.id}`} workspaceId={workspace.id} />
}
function Inbox({ workspaceId }: { workspaceId: number }) {
  const [rows, setRows] = useState<TrustRequest[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const dirty = () => !!root.current?.querySelector('[data-unsaved="true"]')
  useEffect(() => {
    const controller = new AbortController()
    void trustJson(`?workspace_id=${workspaceId}`, {
      signal: controller.signal,
    })
      .then((value) => {
        const next = parseTrustRequests(value, workspaceId)
        if (!controller.signal.aborted) setRows(next)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(failure(e))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [workspaceId, reload])
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {
      if (dirty()) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    const navigate = (event: MouseEvent) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest('a[href]') ||
        !dirty()
      )
        return
      if (!window.confirm('Leave this page and discard unsaved reply text?')) {
        event.preventDefault()
        event.stopPropagation()
      }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', navigate, true)
    return () => {
      window.removeEventListener('beforeunload', unload)
      document.removeEventListener('click', navigate, true)
    }
  }, [])
  return (
    <div ref={root} className="space-y-tc-6">
      <header className="space-y-tc-2">
        <h1 className="text-tc-h1">Incoming Trust requests</h1>
        <p className="text-tc-muted">
          Information requests submitted to your Trust page. Review each reply
          before approving and sending it.
        </p>
      </header>
      <div className="grid items-start gap-tc-6 xl:grid-cols-[minmax(16rem,1fr)_minmax(0,2fr)]">
        <section aria-label="Incoming request list" className={panel}>
          <div className="flex flex-wrap items-center justify-between gap-tc-2">
            <h2 className="text-tc-h2">Requests</h2>
            <Button
              variant="secondary"
              disabled={loading}
              onClick={() => {
                setLoading(true)
                setError('')
                setReload((n) => n + 1)
              }}
            >
              Refresh list
            </Button>
          </div>
          {loading ? (
            <p role="status">Loading incoming requests…</p>
          ) : error ? (
            <Notice>{error}</Notice>
          ) : rows.length === 0 ? (
            <p>No incoming requests</p>
          ) : (
            <ul className="space-y-tc-2">
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    aria-pressed={selected === row.id}
                    className={`w-full rounded-tc-sm border p-tc-3 text-left ${selected === row.id ? 'border-tc-primary bg-tc-surface-raised' : 'border-tc-border'}`}
                    onClick={() => {
                      if (
                        selected === row.id ||
                        !dirty() ||
                        window.confirm(
                          'Discard unsaved reply text and open another request?'
                        )
                      )
                        setSelected(row.id)
                    }}
                  >
                    <span className="block break-words font-semibold">
                      {row.subject || 'Untitled request'}
                    </span>
                    <span className="block break-all text-tc-label text-tc-muted">
                      {row.requester_email}
                    </span>
                    <span className="text-tc-label">
                      {row.status.replaceAll('_', ' ')}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        {selected === null ? (
          <section className={panel}>
            <h2 className="text-tc-h2">Select a request</h2>
            <p>
              Open a request to read its message, attachment and saved replies.
            </p>
          </section>
        ) : (
          <RequestDetail
            key={selected}
            id={selected}
            workspaceId={workspaceId}
          />
        )}
      </div>
    </div>
  )
}
type Operation = 'create' | 'save' | 'approve' | 'send'
function RequestDetail({
  id,
  workspaceId,
}: {
  id: number
  workspaceId: number
}) {
  const alive = useAlive()
  const [request, setRequest] = useState<TrustRequest | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailReload, setDetailReload] = useState(0)
  const [notes, setNotes] = useState<TrustNote[]>([])
  const [notesError, setNotesError] = useState('')
  const [notesReady, setNotesReady] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const [pending, setPending] = useState('')
  const busy = useRef(false)
  const [draft, setDraft] = useState('')
  const [draftError, setDraftError] = useState('')
  const [draftBlocked, setDraftBlocked] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const [downloading, setDownloading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void trustJson(`/${id}`, { signal: controller.signal })
      .then((value) => {
        const next = parseTrustRequest(value, workspaceId, id)
        if (!controller.signal.aborted) setRequest(next)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setDetailError(failure(e))
      })
    return () => controller.abort()
  }, [id, workspaceId, detailReload])
  useEffect(() => {
    const controller = new AbortController()
    void trustJson(`/${id}/notes`, { signal: controller.signal })
      .then((value) => {
        const next = parseTrustNotes(value, id)
        if (!controller.signal.aborted) {
          setNotes(next)
          setNotesReady(true)
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setNotesError(failure(e))
      })
    return () => controller.abort()
  }, [id])
  async function reloadNotes() {
    if (busy.current) return
    busy.current = true
    setPending('reload')
    try {
      const next = parseTrustNotes(await trustJson(`/${id}/notes`), id)
      if (alive.current) {
        setNotes((current) => [
          ...next,
          ...current
            .filter((old) => !next.some((item) => item.id === old.id))
            .map((old) => ({ ...old, delivery_status: 'missing' })),
        ])
        setNotesReady(true)
        setNotesError('')
        setReloadToken((n) => n + 1)
        setDraftBlocked(false)
        setDraftError('')
      }
    } catch (e) {
      if (alive.current) setNotesError(failure(e))
    } finally {
      busy.current = false
      if (alive.current) setPending('')
    }
  }
  async function mutate(
    operation: Operation,
    note: TrustNote | null,
    body?: string
  ) {
    if (busy.current || !request || !notesReady || notesError)
      throw new TrustApiError(409)
    busy.current = true
    setPending(operation)
    try {
      const path =
        operation === 'create'
          ? `/${id}/replies`
          : `/${id}/replies/${note!.id}${operation === 'save' ? '' : `/${operation}`}`
      const payload =
        operation === 'create'
          ? { body }
          : {
              revision: note!.body_revision,
              ...(operation === 'save' ? { body } : {}),
            }
      const saved = parseTrustNote(
        await trustJson(path, {
          method: operation === 'save' ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        }),
        id,
        note?.id
      )
      if (alive.current)
        setNotes((current) =>
          note
            ? current.map((n) => (n.id === saved.id ? saved : n))
            : [...current, saved]
        )
      return saved
    } finally {
      busy.current = false
      if (alive.current) setPending('')
    }
  }
  async function createDraft() {
    if (!draft.trim() || draftBlocked || busy.current) return
    try {
      await mutate('create', null, draft)
      if (alive.current) {
        setDraft('')
        setDraftError('')
      }
    } catch (e) {
      if (alive.current) {
        setDraftError(failure(e))
        setDraftBlocked(!(e instanceof TrustApiError && e.status === 422))
      }
    }
  }
  async function download() {
    if (downloading) return
    setDownloading(true)
    setDownloadError('')
    try {
      const blob = await (await trustFetch(`/${id}/attachment`)).blob()
      if (!alive.current) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = (request?.attachment_filename || 'attachment').replaceAll(
        /[\\/]/g,
        '_'
      )
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      if (alive.current) setDownloadError(failure(e))
    } finally {
      if (alive.current) setDownloading(false)
    }
  }
  if (detailError)
    return (
      <section className={panel}>
        <h2 className="text-tc-h2">Request unavailable</h2>
        <Notice>{detailError}</Notice>
        <Button
          variant="secondary"
          onClick={() => {
            setDetailError('')
            setDetailReload((n) => n + 1)
          }}
        >
          Retry request
        </Button>
      </section>
    )
  if (!request) return <p role="status">Loading request…</p>
  return (
    <section aria-label="Request detail" className={panel}>
      <h2 className="break-words text-tc-h2">
        {request.subject || 'Untitled request'}
      </h2>
      <p className="break-all">
        From {request.requester_name ? `${request.requester_name} — ` : ''}
        {request.requester_email}
      </p>
      <p>
        Status: {request.status.replaceAll('_', ' ')} · Assigned to:{' '}
        {request.assignee || 'Not assigned'}
      </p>
      <p className="whitespace-pre-wrap break-words">{request.message}</p>
      {request.attachment_filename && (
        <div className="space-y-tc-2">
          <p className="break-all">Attachment: {request.attachment_filename}</p>
          <Button
            variant="secondary"
            loading={downloading}
            onClick={() => void download()}
          >
            Download attachment
          </Button>
          {downloadError && <Notice>{downloadError}</Notice>}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-tc-2">
        <h3 className="text-tc-h3">Saved replies and notes</h3>
        <Button
          variant="secondary"
          disabled={!!pending || (!notesReady && !notesError)}
          onClick={() => void reloadNotes()}
        >
          Reload saved replies
        </Button>
      </div>
      {notesError && <Notice>{notesError}</Notice>}
      {!notesReady && !notesError && (
        <p role="status">Loading saved replies…</p>
      )}
      {notesReady && notes.length === 0 && <p>No saved replies or notes</p>}
      {notes.map((note) =>
        note.note_type === 'internal_note' ? (
          <article key={note.id} className={panel}>
            <h4 className="font-semibold">
              Internal note{note.author ? ` by ${note.author}` : ''}
            </h4>
            <p className="whitespace-pre-wrap break-words">{note.body}</p>
          </article>
        ) : (
          <ReplyEditor
            key={note.id}
            note={note}
            busy={!!pending || !!notesError}
            reloadToken={reloadToken}
            mutate={mutate}
          />
        )
      )}
      <section className="space-y-tc-3" aria-label="New reply draft">
        <h3 className="text-tc-h3">New reply draft</h3>
        <p className="text-tc-muted">
          Saving a draft does not send it. Approve its saved revision before
          sending.
        </p>
        <label className="block" htmlFor={`draft-${id}`}>
          Reply text
        </label>
        <textarea
          id={`draft-${id}`}
          className={field}
          rows={5}
          maxLength={10000}
          value={draft}
          data-unsaved={draft.length > 0}
          disabled={!!pending}
          onChange={(event) => setDraft(event.target.value)}
        />
        {draftError && <Notice>{draftError}</Notice>}
        <Button
          disabled={
            !draft.trim() ||
            !!pending ||
            !notesReady ||
            !!notesError ||
            draftBlocked
          }
          onClick={() => void createDraft()}
        >
          Save draft
        </Button>
        {draftBlocked && (
          <p>Reload and inspect saved replies before saving this text again.</p>
        )}
      </section>
    </section>
  )
}
function ReplyEditor({
  note,
  busy,
  reloadToken,
  mutate,
}: {
  note: TrustNote
  busy: boolean
  reloadToken: number
  mutate: (
    operation: Operation,
    note: TrustNote,
    body?: string
  ) => Promise<TrustNote>
}) {
  const alive = useAlive()
  const [seen, setSeen] = useState(note)
  const [seenReload, setSeenReload] = useState(reloadToken)
  const [text, setText] = useState(note.body)
  const [reviewed, setReviewed] = useState(false)
  const [error, setError] = useState('')
  const [blocked, setBlocked] = useState(false)
  if (seen !== note) {
    setSeen(note)
    if (text === seen.body) setText(note.body)
    setReviewed(false)
  }
  if (seenReload !== reloadToken) {
    setSeenReload(reloadToken)
    setError('')
    setBlocked(false)
    setReviewed(false)
  }
  const dirty = text !== note.body
  const actions = replyActions(note)
  async function act(operation: 'save' | 'approve' | 'send') {
    if (busy || blocked) return
    try {
      const saved = await mutate(operation, note, text)
      if (alive.current) {
        if (operation === 'save') setText(saved.body)
        setError('')
        setReviewed(false)
        if (operation === 'send') setBlocked(true)
      }
    } catch (e) {
      if (alive.current) {
        setError(failure(e))
        setBlocked(!(e instanceof TrustApiError && e.status === 422))
      }
    }
  }
  return (
    <article aria-label={`Reply ${note.id}`} className={panel}>
      <h4 className="font-semibold">
        Reply ·{' '}
        {note.body_revision > 0
          ? `revision ${note.body_revision}`
          : 'legacy revision'}
      </h4>
      <p role="status">
        {note.delivery_status === 'missing'
          ? 'Saved reply is no longer available. Local text is kept here for recovery.'
          : deliveryLabel(note.delivery_status)}
      </p>
      {note.approved_revision !== null && (
        <p className="text-tc-label">
          Approval recorded for revision {note.approved_revision}
          {note.approved_at ? ` at ${note.approved_at}` : ''}.
        </p>
      )}
      <label className="block" htmlFor={`reply-${note.id}`}>
        Reply {note.id} text
      </label>
      <textarea
        id={`reply-${note.id}`}
        className={field}
        rows={5}
        maxLength={10000}
        value={text}
        data-unsaved={dirty}
        readOnly={!actions.edit}
        disabled={busy}
        onChange={(event) => {
          setText(event.target.value)
          setReviewed(false)
        }}
      />
      {dirty && (
        <div className="space-y-tc-2">
          <p className="font-semibold">
            Unsaved changes — sending and approval are paused.
          </p>
          <p>Currently saved revision {note.body_revision}:</p>
          <blockquote className="whitespace-pre-wrap break-words border-l-2 border-tc-border pl-tc-3">
            {note.body}
          </blockquote>
        </div>
      )}
      {actions.edit && (
        <label className="flex items-start gap-tc-2">
          <input
            type="checkbox"
            className="mt-1"
            checked={reviewed}
            disabled={busy || blocked}
            onChange={(event) => setReviewed(event.target.checked)}
          />
          <span>
            I reviewed saved revision {note.body_revision} and the text above.
          </span>
        </label>
      )}
      {error && <Notice>{error}</Notice>}
      <div className="flex flex-wrap gap-tc-2">
        {actions.edit && (
          <Button
            variant="secondary"
            disabled={
              busy ||
              blocked ||
              !reviewed ||
              !text.trim() ||
              (!dirty && note.body_revision !== 0)
            }
            onClick={() => void act('save')}
          >
            Save new revision
          </Button>
        )}
        {actions.approve && (
          <Button
            disabled={busy || blocked || dirty || !reviewed}
            style={{
              transitionProperty:
                'border-color, text-decoration-color, fill, stroke',
            }}
            onClick={() => void act('approve')}
          >
            Approve revision
          </Button>
        )}
        {actions.send && (
          <Button
            disabled={busy || blocked || dirty}
            onClick={() => void act('send')}
          >
            Send approved reply
          </Button>
        )}
      </div>
      {blocked && !error && note.delivery_status === 'unavailable' && (
        <p>
          Reload saved replies after the delivery service is available before
          trying again.
        </p>
      )}
      {!actions.edit && (
        <p>
          This saved reply cannot be changed or resent. A different reply needs
          a new draft.
        </p>
      )}
    </article>
  )
}
