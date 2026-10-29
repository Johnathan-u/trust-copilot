// @vitest-environment happy-dom

import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  gapCsv,
  parseGaps,
  useSnapshot,
} from '@/app/dashboard/compliance-gaps/gap-report'

const row = {
  schema_version: 'evidence-gap-ownership/v1',
  id: 91,
  questionnaire_id: 21,
  control_id: null,
  reason: 'Missing current evidence',
  suggested_evidence_doc_title: 'Review record',
  status: 'open',
  priority: 'high',
  age_days: 28,
  owner_user_id: null,
  owner_missing: true,
}
const body = (gaps: unknown[] = [row]) => ({
  schema_version: 'evidence-gap-ownership/v1',
  gaps,
})
const response = () => new Response(JSON.stringify(body()))
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  delete (document as unknown as Record<string, unknown>).hidden
})

describe('evidence gap read contract', () => {
  it('accepts an empty versioned response, rejects unknown or inconsistent data', () => {
    expect(parseGaps(body([]))).toEqual([])
    expect(parseGaps(body())[0].questionnaire_id).toBe(21)
    expect(parseGaps(body([{ ...row, reason: null }]))[0].reason).toBeNull()
    for (const malformed of [
      { gaps: [] },
      { schema_version: 'v2', gaps: [] },
      body([{ ...row, owner_user_id: 42 }]),
      body([row, row]),
      body([{ ...row, age_days: -1 }]),
      body([{ ...row, questionnaire_id: '../other' }]),
    ])
      expect(() => parseGaps(malformed)).toThrow()
  })
  it('exports only human-readable fields, snapshot context and safely quoted text', () => {
    const gaps = parseGaps(
      body([
        {
          ...row,
          suggested_evidence_doc_title: '=SUM(1,2)',
          reason: 'One "quoted" line\nNext line',
        },
      ])
    )
    const csv = gapCsv(gaps, '2026-10-29T18:00:00Z')
    expect(csv).toContain('"\'=SUM(1,2)"')
    expect(csv).toContain('"One ""quoted"" line\nNext line"')
    expect(csv).toContain('2026-10-29T18:00:00Z')
    expect(csv).toContain('"Rows","1"')
    expect(csv).not.toMatch(/questionnaire_id|owner_user_id|workspace_id/)
  })
  it('pauses hidden polling, retains a failed snapshot, and clears failure after recovery', async () => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    })
    const fetcher = vi.fn().mockImplementation(async () => response())
    vi.stubGlobal('fetch', fetcher)
    const { result, unmount } = renderHook(() =>
      useSnapshot('/api/evidence-gaps', parseGaps)
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data).toHaveLength(1)
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000)
    })
    expect(fetcher).toHaveBeenCalledTimes(1)
    fetcher.mockResolvedValueOnce(new Response('{}', { status: 500 }))
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    })
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data).toHaveLength(1)
    expect(result.current.failure).not.toBeNull()
    await act(async () => {
      result.current.retry()
      await vi.advanceTimersByTimeAsync(1)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.failure).toBeNull()
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('removes previously loaded data when permission is denied on refresh', async () => {
    vi.useFakeTimers()
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(new Response('{}', { status: 403 }))
    vi.stubGlobal('fetch', fetcher)
    const { result } = renderHook(() =>
      useSnapshot('/api/evidence-gaps', parseGaps)
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data).toHaveLength(1)
    await act(async () => {
      result.current.retry()
      await vi.advanceTimersByTimeAsync(1)
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data).toBeNull()
    expect(result.current.failure?.kind).toBe('forbidden')
  })
  it('aborts and ignores a pending read when the workspace page is removed', async () => {
    vi.useFakeTimers()
    let signal: AbortSignal | undefined
    const fetcher = vi.fn().mockImplementation((_url, options) => {
      signal = options.signal
      return new Promise(() => {})
    })
    vi.stubGlobal('fetch', fetcher)
    const { unmount } = renderHook(() =>
      useSnapshot('/api/evidence-gaps', parseGaps)
    )
    unmount()
    expect(signal?.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })
})
