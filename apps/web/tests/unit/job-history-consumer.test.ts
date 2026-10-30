import { describe, expect, it } from 'vitest'
import {
  actionFor,
  cursorForWorkspace,
  jobsHref,
  objectLink,
  parseJobDetail,
  parseJobHistory,
} from '@/lib/job-history-consumer'

const row = {
  id: 41,
  kind: 'generate_answers',
  status: 'running',
  attempt: 1,
  max_attempts: 3,
  created_at: '2026-10-30T12:00:00',
  started_at: null,
  completed_at: null,
  next_attempt_at: null,
  retry_scheduled: false,
  retries_exhausted: false,
  charge_uncertain: true,
  progress: { generated: 2, total: 5 },
  outcome: null,
  object_ref: { type: 'questionnaire', id: 9 },
}
describe('safe persisted job consumer', () => {
  it('projects history and never retains arbitrary data', () => {
    const value = parseJobHistory({
      items: [
        {
          ...row,
          payload: 'SECRET',
          result: 'SECRET',
          error: 'SECRET',
          error_detail: { message: 'SECRET', request_id: 'SECRET' },
        },
      ],
      next_before_id: null,
    })
    expect(value.items[0].progress).toEqual({ generated: 2, total: 5 })
    expect(objectLink(value.items[0])).toEqual({
      href: '/dashboard/questionnaires/9',
      label: 'Open questionnaire',
    })
    expect(JSON.stringify(value)).not.toContain('SECRET')
  })
  it.each([
    {},
    { items: null, next_before_id: null },
    { items: [], next_before_id: 1 },
    { items: [row, row], next_before_id: null },
    { items: [row], next_before_id: 42 },
  ])('rejects malformed pages instead of a false empty state: %j', (value) => {
    expect(() => parseJobHistory(value)).toThrow()
  })
  it('checks descending order and the requested cursor', () => {
    expect(() =>
      parseJobHistory(
        { items: [{ ...row, id: 42 }, row], next_before_id: 41 },
        42
      )
    ).toThrow()
    expect(
      parseJobHistory(
        { items: [row, { ...row, id: 40 }], next_before_id: 40 },
        42
      ).nextBeforeId
    ).toBe(40)
  })
  it('shows unknown kinds and states without echoing server strings or actions', () => {
    const job = parseJobHistory({
      items: [{ ...row, kind: 'SECRET', status: 'SECRET' }],
      next_before_id: null,
    }).items[0]
    expect(job.kind).toBeNull()
    expect(job.status).toBeNull()
    expect(actionFor(job, true)).toBeNull()
    expect(objectLink(job)).toBeNull()
    expect(JSON.stringify(job)).not.toContain('SECRET')
  })
  it.each([
    { generated: -1, total: 4 },
    { generated: 5, total: 4 },
    { generated: true, total: 4 },
    { generated: 1, total: Number.MAX_SAFE_INTEGER + 1 },
  ])('drops unsafe progress %j', (progress) => {
    expect(
      parseJobHistory({ items: [{ ...row, progress }], next_before_id: null })
        .items[0].progress
    ).toBeNull()
  })
  it('legacy detail projects counters, but cannot grant object access or expose provider text', () => {
    const value = parseJobDetail(
      {
        ...row,
        object_ref: { type: 'document', id: 8 },
        error: 'SECRET',
        error_code: 'SECRET',
        result: { generated: 3, total: 5, url: 'SECRET', document_id: 8 },
        payload: 'SECRET',
      },
      41
    )
    expect(value.progress).toEqual({ generated: 3, total: 5 })
    expect(value.objectRef).toBeNull()
    expect(JSON.stringify(value)).not.toContain('SECRET')
  })
  it('requires the expected identity and actual action acknowledgment', () => {
    expect(() => parseJobDetail(row, 42)).toThrow()
    expect(() =>
      parseJobDetail({ ...row, charge_uncertain: undefined }, 41)
    ).toThrow()
    expect(() => parseJobDetail(row, 41, 'cancel')).toThrow()
    expect(() =>
      parseJobDetail({ ...row, status: 'completed' }, 41, 'retry')
    ).toThrow()
    expect(
      parseJobDetail({ ...row, status: 'cancelled' }, 41, 'cancel').status
    ).toBe('cancelled')
    expect(
      parseJobDetail({ ...row, status: 'queued' }, 41, 'retry').status
    ).toBe('queued')
  })
  it('uses only current checked history links with matching type', () => {
    const read = (object_ref: unknown, kind = 'index_document') =>
      parseJobHistory({
        items: [{ ...row, kind, object_ref }],
        next_before_id: null,
      }).items[0]
    expect(objectLink(read({ type: 'document', id: 2 }))).toEqual({
      href: '/dashboard/documents',
      label: 'Open document library',
    })
    for (const ref of [
      null,
      { type: 'questionnaire', id: 2 },
      { type: 'document', id: '2' },
      { type: 'document', id: -2 },
      { type: 'document', id: 2147483648 },
    ])
      expect(objectLink(read(ref))).toBeNull()
  })
  it('binds reload cursors to the current workspace and rejects invalid saved cursors', () => {
    expect(jobsHref(7, 41)).toBe('/dashboard/jobs?workspace_id=7&before_id=41')
    expect(
      cursorForWorkspace(new URLSearchParams('workspace_id=7&before_id=41'), 7)
    ).toBe(41)
    expect(
      cursorForWorkspace(new URLSearchParams('workspace_id=7&before_id=41'), 8)
    ).toBeNull()
    expect(
      cursorForWorkspace(new URLSearchParams('before_id=41'), 7)
    ).toBeNull()
    for (const value of ['0', '-1', '1.5', '1e2', 'secret', '9007199254740992'])
      expect(() =>
        cursorForWorkspace(
          new URLSearchParams(`workspace_id=7&before_id=${value}`),
          7
        )
      ).toThrow()
  })
  it('requires current admin permission and known eligible lifecycle for actions', () => {
    const job = parseJobHistory({ items: [row], next_before_id: null }).items[0]
    expect(actionFor(job, false)).toBeNull()
    expect(actionFor(job, true)).toBe('cancel')
    expect(actionFor({ ...job, status: 'failed' }, true)).toBe('retry')
    expect(actionFor({ ...job, status: 'completed' }, true)).toBeNull()
  })
})
