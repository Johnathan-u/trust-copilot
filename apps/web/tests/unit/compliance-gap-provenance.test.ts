// @vitest-environment happy-dom

import { createElement, StrictMode } from 'react'
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  readRecommendations,
  readRecommendationEvidence,
  readRecommendationQuestion,
} from '@/app/dashboard/compliance-gaps/recommendation-contract'
import {
  Recommendations,
  useRecommendationEvidence,
  useRecommendationQuestion,
} from '@/app/dashboard/compliance-gaps/recommendations'

const questionSource = { question_id: 31, questionnaire_id: 21 }
const questionnaire = {
  id: 21,
  filename: 'Customer questionnaire',
  questions: [
    { id: 31, text: 'How do you review access?', section: 'Access management' },
  ],
}

const recommendation = {
  title: 'Access review record',
  improves_questions: 5,
  evidence_ids: [71],
  control_ids: [41],
  question_ids: [31, 32],
  question_sources: [questionSource, { question_id: 32, questionnaire_id: 22 }],
}
const evidence = {
  id: 71,
  workspace_id: 7,
  title: 'Quarterly review',
  source_type: 'document',
  document_id: 51,
  created_at: null,
}
const reply = (body: unknown = evidence, status = 200) =>
  new Response(JSON.stringify(body), { status })

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('recommendation provenance', () => {
  it('keeps every source identifier and the independent reported suggestion count', () => {
    expect(readRecommendations([recommendation])).toEqual([recommendation])
    expect(readRecommendations([])).toEqual([])
    expect(
      readRecommendations([
        { title: 'Legacy suggestion', improves_questions: 2 },
      ])
    ).toEqual([
      {
        title: 'Legacy suggestion',
        improves_questions: 2,
        evidence_ids: [],
        control_ids: [],
        question_ids: [],
        question_sources: [],
      },
    ])
  })

  it('keeps absent question mappings unavailable and rejects ambiguous or invented pairs', () => {
    expect(
      readRecommendations([
        { ...recommendation, question_sources: undefined },
      ])[0].question_sources
    ).toEqual([])
    for (const sources of [
      null,
      {},
      [null],
      [{ question_id: 31 }],
      [{ ...questionSource, questionnaire_id: '../other' }],
      [{ ...questionSource, question_id: 33 }],
      [questionSource, { ...questionSource, questionnaire_id: 22 }],
    ])
      expect(() =>
        readRecommendations([{ ...recommendation, question_sources: sources }])
      ).toThrow()
  })

  it('requires the explicit questionnaire and exact unique question before showing source details', () => {
    expect(
      readRecommendationQuestion(questionnaire, questionSource, 7)
    ).toEqual({
      questionId: 31,
      questionnaireId: 21,
      questionnaireTitle: 'Customer questionnaire',
      text: 'How do you review access?',
      section: 'Access management',
    })
    for (const body of [
      { ...questionnaire, id: 22 },
      { ...questionnaire, workspace_id: 8 },
      { ...questionnaire, questions: [] },
      {
        ...questionnaire,
        questions: [{ ...questionnaire.questions[0], id: 32 }],
      },
      {
        ...questionnaire,
        questions: [questionnaire.questions[0], questionnaire.questions[0]],
      },
      {
        ...questionnaire,
        questions: [{ ...questionnaire.questions[0], text: null }],
      },
    ])
      expect(() =>
        readRecommendationQuestion(body, questionSource, 7)
      ).toThrow()
  })

  it('uses only the mapped workspace-scoped questionnaire read and never scans a list', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(reply(questionnaire))
    vi.stubGlobal('fetch', fetcher)
    const { result } = renderHook(() =>
      useRecommendationQuestion(questionSource, 7)
    )
    await act(async () => {})
    expect(result.current.data?.text).toBe('How do you review access?')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe(
      '/api/questionnaires/21?workspace_id=7'
    )
    expect(fetcher.mock.calls[0][1].method).toBeUndefined()
  })

  it('does not reuse one question detail for another question in the same questionnaire', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(reply(questionnaire))
      .mockImplementationOnce(() => new Promise(() => {}))
    vi.stubGlobal('fetch', fetcher)
    const { result, rerender } = renderHook(
      ({ source }) => useRecommendationQuestion(source, 7),
      { initialProps: { source: questionSource } }
    )
    await act(async () => {})
    expect(result.current.data?.questionId).toBe(31)
    await act(async () =>
      rerender({ source: { ...questionSource, question_id: 32 } })
    )
    expect(result.current.data).toBeNull()
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
  })

  it('fetches a source only on disclosure and shows only verified navigation targets', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(reply(evidence))
      .mockResolvedValueOnce(reply(questionnaire))
    vi.stubGlobal('fetch', fetcher)
    const view = render(
      createElement(Recommendations, {
        recommendations: [recommendation],
        workspaceId: 7,
      })
    )
    expect(fetcher).not.toHaveBeenCalled()
    expect(
      view
        .getByRole('link', { name: 'View control source 1' })
        .getAttribute('href')
    ).toBe('/dashboard/controls/41')
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View evidence source 1' })
      )
    )
    expect(view.getByText('Quarterly review')).toBeTruthy()
    expect(
      view.queryByRole('link', { name: 'Open source questionnaire' })
    ).toBeNull()
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View question source 1' })
      )
    )
    expect(view.getByText('How do you review access?')).toBeTruthy()
    expect(
      view
        .getByRole('link', { name: 'Open source questionnaire' })
        .getAttribute('href')
    ).toBe('/dashboard/questionnaires/21')
    expect(fetcher).toHaveBeenCalledTimes(2)
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'Hide evidence source 1' })
      )
    )
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
  })

  it('starts only one read per disclosure when StrictMode replays mount effects', async () => {
    const fetcher = vi.fn((url: string) =>
      Promise.resolve(
        reply(url.includes('/evidence/') ? evidence : questionnaire)
      )
    )
    vi.stubGlobal('fetch', fetcher)
    const view = render(
      createElement(
        StrictMode,
        null,
        createElement(Recommendations, {
          recommendations: [recommendation],
          workspaceId: 7,
        })
      )
    )
    expect(fetcher).not.toHaveBeenCalled()
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View evidence source 1' })
      )
    )
    expect(view.getByText('Quarterly review')).toBeTruthy()
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View question source 1' })
      )
    )
    expect(view.getByText('How do you review access?')).toBeTruthy()
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/compliance/evidence/71',
      '/api/questionnaires/21?workspace_id=7',
    ])
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'Hide evidence source 1' })
      )
    )
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View evidence source 1' })
      )
    )
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/compliance/evidence/71',
      '/api/questionnaires/21?workspace_id=7',
      '/api/compliance/evidence/71',
    ])
  })

  it('labels sources by list position while retaining arbitrary identifiers in requests and links', async () => {
    const sources = {
      ...recommendation,
      evidence_ids: [871002, 871001],
      control_ids: [841002, 841001],
      question_ids: [831002, 831001],
      question_sources: [
        { question_id: 831002, questionnaire_id: 821002 },
        { question_id: 831001, questionnaire_id: 821001 },
      ],
    }
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(reply({ ...evidence, id: 871002 }))
      .mockResolvedValueOnce(
        reply({
          ...questionnaire,
          id: 821001,
          questions: [{ ...questionnaire.questions[0], id: 831001 }],
        })
      )
    vi.stubGlobal('fetch', fetcher)
    const view = render(
      createElement(Recommendations, {
        recommendations: [sources],
        workspaceId: 7,
      })
    )
    const identifiers =
      /\b(?:871002|871001|841002|841001|831002|831001|821002|821001)\b/
    expect(view.container.textContent).not.toMatch(identifiers)
    expect(
      view
        .getByRole('link', { name: 'View control source 1' })
        .getAttribute('href')
    ).toBe('/dashboard/controls/841002')
    expect(
      view
        .getByRole('link', { name: 'View control source 2' })
        .getAttribute('href')
    ).toBe('/dashboard/controls/841001')
    expect(
      view.getByRole('button', { name: 'View evidence source 2' })
    ).toBeTruthy()
    expect(
      view.getByRole('button', { name: 'View question source 1' })
    ).toBeTruthy()

    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View evidence source 1' })
      )
    )
    await act(async () =>
      fireEvent.click(
        view.getByRole('button', { name: 'View question source 2' })
      )
    )

    expect(view.getByText('Quarterly review')).toBeTruthy()
    expect(view.getByText('How do you review access?')).toBeTruthy()
    expect(view.container.textContent).not.toMatch(identifiers)
    expect(
      view
        .getByRole('link', { name: 'Open source questionnaire' })
        .getAttribute('href')
    ).toBe('/dashboard/questionnaires/821001')
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/compliance/evidence/871002',
      '/api/questionnaires/821001?workspace_id=7',
    ])
    for (const [, options] of fetcher.mock.calls)
      expect(options.method).toBeUndefined()
  })

  it('fails malformed lists or identifiers instead of silently dropping a recommendation', () => {
    for (const value of [null, {}, [null], [{ ...recommendation, title: 42 }]])
      expect(() => readRecommendations(value)).toThrow()
    for (const field of ['evidence_ids', 'control_ids', 'question_ids']) {
      for (const value of [
        null,
        71,
        ['71'],
        [0],
        [-1],
        [1.5],
        [Infinity],
        [NaN],
        [Number.MAX_SAFE_INTEGER + 1],
        ['../other'],
        [71, 71],
      ])
        expect(() =>
          readRecommendations([{ ...recommendation, [field]: value }])
        ).toThrow()
    }
    expect(() =>
      readRecommendations([{ ...recommendation, improves_questions: -1 }])
    ).toThrow()
  })

  it('checks the evidence identity and workspace before rendering source content', () => {
    expect(readRecommendationEvidence(evidence, 71, 7)).toEqual(evidence)
    for (const value of [
      { ...evidence, id: 72 },
      { ...evidence, workspace_id: 8 },
      { ...evidence, title: null },
      { ...evidence, document_id: '../other' },
      { ...evidence, source_type: null },
      null,
    ])
      expect(() => readRecommendationEvidence(value, 71, 7)).toThrow()
  })

  it('loads only the selected evidence through a read and recovers after unavailable or denied replies', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    for (const status of [403, 404, 500]) {
      fetcher.mockResolvedValueOnce(
        reply({ detail: 'Private error content' }, status)
      )
      const { result, unmount } = renderHook(() =>
        useRecommendationEvidence(71, 7)
      )
      await act(async () => {})
      expect(result.current.data).toBeNull()
      expect(result.current.failure).not.toBeNull()
      expect(JSON.stringify(result.current.failure)).not.toContain(
        'Private error content'
      )
      fetcher.mockResolvedValueOnce(reply())
      await act(async () => result.current.retry())
      expect(result.current.failure).toBeNull()
      expect(result.current.data?.title).toBe('Quarterly review')
      unmount()
    }
    for (const [url, options] of fetcher.mock.calls) {
      expect(url).toBe('/api/compliance/evidence/71')
      expect(options.credentials).toBe('include')
      expect(options.method).toBeUndefined()
    }
  })

  it('does not display foreign or mismatched evidence returned with HTTP success', async () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    for (const body of [
      { ...evidence, workspace_id: 8 },
      { ...evidence, id: 72 },
    ]) {
      fetcher.mockResolvedValueOnce(reply(body))
      const { result, unmount } = renderHook(() =>
        useRecommendationEvidence(71, 7)
      )
      await act(async () => {})
      expect(result.current.data).toBeNull()
      expect(result.current.failure).not.toBeNull()
      unmount()
    }
  })

  it('bounds a source read and ignores a response that arrives after timeout', async () => {
    vi.useFakeTimers()
    let complete: (response: Response) => void = () => {}
    const fetcher = vi.fn().mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          complete = resolve
        })
    )
    vi.stubGlobal('fetch', fetcher)
    const { result, unmount } = renderHook(() =>
      useRecommendationEvidence(71, 7)
    )
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    expect(result.current.failure).not.toBeNull()
    await act(async () => complete(reply()))
    expect(result.current.data).toBeNull()
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('aborts and ignores late source reads after a workspace change or close', async () => {
    let complete: (response: Response) => void = () => {}
    const fetcher = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            complete = resolve
          })
      )
      .mockResolvedValueOnce(
        reply({
          ...evidence,
          workspace_id: 8,
          title: 'Second workspace source',
        })
      )
    vi.stubGlobal('fetch', fetcher)
    const { result, rerender, unmount } = renderHook(
      ({ workspaceId }) => useRecommendationEvidence(71, workspaceId),
      { initialProps: { workspaceId: 7 } }
    )
    await act(async () => rerender({ workspaceId: 8 }))
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    await act(async () => complete(reply()))
    expect(result.current.data?.title).toBe('Second workspace source')
    unmount()
    expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true)
  })
})
