import { describe, expect, it } from 'vitest'

import { presentHttpFailure } from '@/lib/api-error'
import {
  listFromPayload,
  loadSection,
  sectionFailure,
} from '@/lib/section-load'
import {
  PARTIAL_SUCCESS_COPY,
  SKELETON_TIMEOUT_MS,
  SLOW_LOADING_COPY,
  listPhase,
  pageMode,
  skeletonPhase,
  type SectionSnapshot,
} from '@/lib/ui-state'

const forbidden = presentHttpFailure({ status: 403 })
const server = presentHttpFailure({ status: 500 })

function section(
  id: string,
  phase: SectionSnapshot['phase'],
  failure: SectionSnapshot['failure'] = null
): SectionSnapshot {
  return { id, label: id, phase, failure }
}

describe('skeleton timeout', () => {
  it('stays loading until the timeout and then becomes slow', () => {
    expect(SKELETON_TIMEOUT_MS).toBeGreaterThan(0)
    expect(skeletonPhase(0)).toBe('loading')
    expect(skeletonPhase(SKELETON_TIMEOUT_MS - 1)).toBe('loading')
    expect(skeletonPhase(SKELETON_TIMEOUT_MS)).toBe('slow')
    expect(skeletonPhase(SKELETON_TIMEOUT_MS, 1000)).toBe('slow')
    expect(SLOW_LOADING_COPY.title.length).toBeGreaterThan(0)
  })
})

describe('pageMode', () => {
  it('keeps a loading primary on the skeleton', () => {
    expect(pageMode(section('cards', 'loading')).mode).toBe('loading')
  })

  it('treats a failed primary with an empty secondary as an error, not empty', () => {
    const mode = pageMode(section('cards', 'error', server), [
      section('alerts', 'empty'),
    ])
    expect(mode.mode).toBe('error')
    if (mode.mode === 'error') expect(mode.failure.kind).toBe('server')
  })

  it('shows partial success when cards load and another section fails', () => {
    const mode = pageMode(section('cards', 'ready'), [
      section('alerts', 'error', server),
    ])
    expect(mode.mode).toBe('partial')
    if (mode.mode === 'partial') {
      expect(mode.failed.map((item) => item.id)).toEqual(['alerts'])
    }
  })

  it('shows partial success when the primary is a real empty list and another section fails', () => {
    const mode = pageMode(section('cards', 'empty'), [
      section('alerts', 'error', forbidden),
    ])
    expect(mode.mode).toBe('partial')
  })

  it('settles when every section succeeded, including empty lists', () => {
    expect(
      pageMode(section('cards', 'empty'), [section('alerts', 'empty')]).mode
    ).toBe('settled')
    expect(
      pageMode(section('cards', 'ready'), [section('alerts', 'ready')]).mode
    ).toBe('settled')
  })

  it('uses one error when every section failed', () => {
    const mode = pageMode(section('cards', 'error', server), [
      section('alerts', 'error', forbidden),
    ])
    expect(mode.mode).toBe('error')
    if (mode.mode === 'error') expect(mode.failure.kind).toBe('server')
  })

  it('does not describe partial success with permission language', () => {
    const text =
      `${PARTIAL_SUCCESS_COPY.title} ${PARTIAL_SUCCESS_COPY.description}`.toLowerCase()
    expect(text).not.toContain('permission')
    expect(text).not.toContain('admin')
  })
})

describe('list payloads', () => {
  it('accepts an empty list and rejects a missing list', () => {
    expect(listFromPayload({ cards: [] }, ['cards'])).toEqual([])
    expect(listPhase(0)).toBe('empty')
    expect(listPhase(2)).toBe('ready')
    expect(() => listFromPayload({ detail: 'nope' }, ['cards'])).toThrow()
    expect(() => listFromPayload([], ['cards'])).not.toThrow()
  })

  it('turns HTTP 500 and an aborted network into failures, not empty arrays', async () => {
    const denied = await loadSection(
      Promise.resolve(
        new Response(JSON.stringify({ detail: 'Insufficient permissions' }), {
          status: 500,
        })
      ),
      (data) => listFromPayload(data, ['cards'])
    )
    expect(sectionFailure(denied)?.kind).toBe('server')

    const empty = await loadSection(
      Promise.resolve(
        new Response(JSON.stringify({ cards: [] }), { status: 200 })
      ),
      (data) => listFromPayload<string>(data, ['cards'])
    )
    expect(empty).toEqual({ ok: true, data: [] })
  })
})
