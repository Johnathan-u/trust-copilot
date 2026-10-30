// @vitest-environment happy-dom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  parseEvidenceChoices,
  useGapMutation,
} from '@/app/dashboard/compliance-gaps/gap-actions'

const row = {
  schema_version: 'evidence-gap-ownership/v1',
  id: 91,
  workspace_id: 7,
  questionnaire_id: 21,
  control_id: null,
  reason: 'Missing current evidence',
  suggested_evidence_doc_title: 'Review record',
  status: 'resolved',
  priority: 'settled',
  age_days: 28,
  owner_user_id: null,
  owner_missing: true,
  resolved: true,
  notified: false,
}
const reply = (body: unknown = row, status = 200) =>
  new Response(JSON.stringify(body), { status })

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('gap action acknowledgments', () => {
  it('retains a retry key after a lost response and confirms notification failure separately', async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValueOnce(reply())
    vi.stubGlobal('fetch', fetcher)
    const confirmed = vi.fn()
    const { result } = renderHook(() => useGapMutation(91, 7, confirmed))
    await act(async () => {
      await result.current.submit({ kind: 'resolve', evidenceId: 71 })
    })
    expect(confirmed).not.toHaveBeenCalled()
    expect(result.current.error).toMatch(/Could not confirm/)
    await act(async () => {
      await result.current.submit({ kind: 'resolve', evidenceId: 71 })
    })
    expect(fetcher.mock.calls[0][1].headers['Idempotency-Key']).toBe(
      fetcher.mock.calls[1][1].headers['Idempotency-Key']
    )
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
      evidence_id: 71,
    })
    expect(confirmed).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'resolved' }),
      true
    )
  })

  it('rejects incorrect acknowledgments and does not trust arbitrary backend error text', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    const confirmed = vi.fn()
    const { result } = renderHook(() => useGapMutation(91, 7, confirmed))
    for (const body of [
      { ...row, id: 92 },
      { ...row, workspace_id: 8 },
      { ...row, resolved: false },
      { ...row, status: 'open' },
      {},
    ]) {
      fetcher.mockResolvedValueOnce(reply(body))
      await act(async () => {
        await result.current.submit({ kind: 'resolve', evidenceId: 71 })
      })
      expect(result.current.error).toMatch(/Could not confirm/)
    }
    fetcher.mockResolvedValueOnce(
      reply({ detail: { rule: 'private_rule_code' } }, 400)
    )
    await act(async () => {
      await result.current.submit({ kind: 'resolve', evidenceId: 71 })
    })
    expect(result.current.error).toMatch(/approved, current evidence/)
    expect(result.current.error).not.toContain('private_rule_code')
    expect(confirmed).not.toHaveBeenCalled()
  })

  it('uses distinct keys for changed intent and handles permission and concurrency denials', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(reply({}, 403))
      .mockResolvedValueOnce(reply({}, 409))
    vi.stubGlobal('fetch', fetcher)
    const confirmed = vi.fn()
    const { result } = renderHook(() => useGapMutation(91, 7, confirmed))
    await act(async () => {
      await result.current.submit({ kind: 'accepted' })
    })
    expect(result.current.error).toMatch(/permission/)
    await act(async () => {
      await result.current.submit({ kind: 'dismissed' })
    })
    expect(result.current.error).toMatch(/changed/)
    expect(fetcher.mock.calls[0][1].headers['Idempotency-Key']).not.toBe(
      fetcher.mock.calls[1][1].headers['Idempotency-Key']
    )
    expect(confirmed).not.toHaveBeenCalled()
  })

  it('ignores a late acknowledgment after workspace teardown and aborts the request', async () => {
    let finish: (response: Response) => void = () => {}
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve
        })
    )
    vi.stubGlobal('fetch', fetcher)
    const confirmed = vi.fn()
    const { result, unmount } = renderHook(() =>
      useGapMutation(91, 7, confirmed)
    )
    let pending: Promise<void> | undefined
    act(() => {
      pending = result.current.submit({ kind: 'accepted' })
    })
    unmount()
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    await act(async () => {
      finish(reply({ ...row, status: 'accepted' }))
      await pending
    })
    expect(confirmed).not.toHaveBeenCalled()
  })

  it('validates evidence search pages without treating approval as proof of gap eligibility', () => {
    expect(
      parseEvidenceChoices({ total: 0, offset: 0, limit: 25, items: [] }).items
    ).toEqual([])
    const choice = {
      id: 71,
      title: 'Quarterly review',
      source_type: 'document',
      approval_status: 'approved',
      created_at: '2026-10-29T12:00:00Z',
    }
    expect(
      parseEvidenceChoices({ total: 1, offset: 0, limit: 25, items: [choice] })
        .items[0].title
    ).toBe('Quarterly review')
    for (const body of [
      {},
      {
        total: 1,
        offset: 0,
        limit: 25,
        items: [{ ...choice, approval_status: 'pending' }],
      },
      { total: -1, offset: 0, limit: 25, items: [] },
    ])
      expect(() => parseEvidenceChoices(body)).toThrow()
  })
})
