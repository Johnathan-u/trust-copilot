import { describe, expect, it } from 'vitest'

import {
  ANSWER_STATUS_LABEL,
  answerStatusLabel,
  formatGenerationElapsed,
  generationPhaseMessage,
  isInsufficientAnswerText,
} from '@/lib/ai-review-copy'

describe('answerStatusLabel', () => {
  it('maps API statuses to UI labels', () => {
    expect(answerStatusLabel('pending')).toBe('Not reviewed')
    expect(answerStatusLabel('insufficient_evidence')).toBe('Needs more evidence')
    expect(answerStatusLabel('approved')).toBe('Approved')
  })

  it('treats a missing status as pending and passes unknown statuses through', () => {
    expect(answerStatusLabel(undefined)).toBe(ANSWER_STATUS_LABEL.pending)
    expect(answerStatusLabel('archived')).toBe('archived')
  })
})

describe('generationPhaseMessage', () => {
  it('describes queued and running jobs case-insensitively', () => {
    expect(generationPhaseMessage('QUEUED').title).toBe('Queued')
    expect(generationPhaseMessage('running').title).toBe('Generating draft answers')
  })

  it('falls back for unknown or empty job status', () => {
    for (const s of [null, undefined, '', 'completed', 'failed']) {
      expect(generationPhaseMessage(s).title).toBe('Checking progress')
    }
  })
})

describe('formatGenerationElapsed', () => {
  it.each([
    [0, '0:00'],
    [5, '0:05'],
    [59, '0:59'],
    [60, '1:00'],
    [754, '12:34'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatGenerationElapsed(seconds)).toBe(expected)
  })
})

describe('isInsufficientAnswerText', () => {
  it('trusts the API insufficient_evidence status', () => {
    expect(isInsufficientAnswerText('We encrypt data at rest with AES-256.', 'insufficient_evidence')).toBe(
      true
    )
  })

  it('flags empty and explicit insufficient-evidence answers', () => {
    expect(isInsufficientAnswerText(null)).toBe(true)
    expect(isInsufficientAnswerText('   ')).toBe(true)
    expect(isInsufficientAnswerText('Insufficient evidence.')).toBe(true)
    expect(isInsufficientAnswerText('INSUFFICIENT EVIDENCE to answer this question in full detail.')).toBe(
      true
    )
  })

  it('flags hedged answers, normalising case and whitespace', () => {
    expect(
      isInsufficientAnswerText(
        'The   provided documentation\n does NOT specify whether backups are tested.',
        'draft'
      )
    ).toBe(true)
  })

  it('only inspects the head of long answers', () => {
    const long = 'Yes. '.repeat(100) + 'the evidence does not explicitly state this.'
    expect(isInsufficientAnswerText(long, 'draft')).toBe(false)
  })

  it('does not flag substantive answers', () => {
    expect(isInsufficientAnswerText('Yes. MFA is enforced for all workforce accounts via SSO.', 'draft')).toBe(
      false
    )
  })
})
