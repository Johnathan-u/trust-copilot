import Link from 'next/link'
import { Card } from '@/components/ui'

export default function ReviewListPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--tc-muted)]">Answer review</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-[var(--tc-text)]">Review draft answers</h1>
        <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-[var(--tc-muted)]">
          Open a questionnaire to see questions, supporting evidence, and draft answers. Approve or edit before export.
        </p>
      </div>
      <Card className="border border-[var(--tc-border)]/80 bg-[var(--tc-surface)]/60 p-8">
        <h2 className="text-lg font-semibold text-[var(--tc-text)]">Choose a file</h2>
        <p className="mt-2 text-sm leading-relaxed text-[var(--tc-muted)]">
          Draft answers are organized by questionnaire. Start from your questionnaire list, then use{' '}
          <span className="font-medium text-[var(--tc-text)]">Review answers</span> on the file you want.
        </p>
        <Link
          href="/dashboard/questionnaires"
          className="tc-btn-primary mt-tc-6 inline-flex min-h-tc-8 items-center justify-center gap-tc-2 rounded-tc-sm px-tc-4 py-tc-3 text-tc-label font-semibold"
        >
          Go to questionnaires
        </Link>
      </Card>
    </div>
  )
}
