/**
 * Human-facing copy for the answer review workflow.
 * Keep backend status values (pending, draft, …) as-is for API compatibility;
 * labels here are for UI only.
 */

/** Maps API answer.status to short labels shown in filters and the status column. */
export const ANSWER_STATUS_LABEL: Record<string, string> = {
  pending: 'Not reviewed',
  draft: 'Draft answer',
  insufficient_evidence: 'Needs more evidence',
  approved: 'Approved',
  rejected: 'Rejected',
  flagged: 'Needs attention',
}

export function answerStatusLabel(status: string | undefined): string {
  const key = status ?? 'pending'
  return ANSWER_STATUS_LABEL[key] ?? key
}

/** Job.status from GET /api/jobs/{id} (lowercase). */
export function generationPhaseMessage(jobStatus: string | null | undefined): {
  title: string
  subtitle: string
} {
  const s = (jobStatus ?? '').toLowerCase()
  if (s === 'queued') {
    return {
      title: 'Queued',
      subtitle: 'Your request is in line. Processing usually starts within a few seconds.',
    }
  }
  if (s === 'running') {
    return {
      title: 'Generating draft answers',
      subtitle:
        'AI is drafting answers from your indexed evidence. You can keep using filters and scrolling on this page.',
    }
  }
  return {
    title: 'Checking progress',
    subtitle: 'Waiting for an update from the server.',
  }
}

export function formatGenerationElapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** Must stay aligned with `answer_evidence_policy.is_insufficient_answer_text` (Python). */
const HEDGE_INSUFFICIENT_NEEDLES = [
  'the provided documentation does not specify',
  'the provided documentation does not explicitly',
  'the documentation does not specify whether',
  'the documentation does not explicitly',
  'the evidence does not explicitly state',
  'the evidence does not specify whether',
  'the evidence does not explicitly',
  'does not explicitly state whether',
  'does not specify whether the',
  'does not explicitly address whether',
  'provided documentation does not explicitly state',
] as const

/**
 * True when the row should be bucketed as “needs more evidence” (API status or text heuristics).
 * Used for hero counts and filters; legacy rows may rely on text when status was still `draft`.
 */
export function isInsufficientAnswerText(
  text: string | null | undefined,
  status?: string | null,
): boolean {
  if (status === 'insufficient_evidence') return true
  const t = (text ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
  if (!t) return true
  if (t === 'insufficient evidence' || t === 'insufficient evidence.') return true
  if (t.startsWith('insufficient evidence') && t.length < 80) return true
  if (t.startsWith('insufficient evidence')) return true
  const head = t.slice(0, 360)
  return HEDGE_INSUFFICIENT_NEEDLES.some((n) => head.includes(n))
}
