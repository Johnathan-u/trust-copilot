# Questionnaire replay

Operator notes for a repeated parse of one questionnaire (TC-09-006). No new
setting. No migration.

A parse job is tied to the storage key in its payload. The questionnaire row
keeps the current key. The worker compares the parsed questions with the rows
already stored. The comparison uses `content_hash` (the normalized question
text) and `original_file_hash` (the file bytes). It does not stop just because
a question row exists.

## Same bytes

Re-delivering the same job, or running a second job for the same bytes, does
not insert another copy of the questions. The job outcome is `already_applied`
when that job already committed the questions, and `reconciled` when another
job did. Approved answers stay on the same question ids. Nothing is deleted.

## Replaced file

When the questionnaire's storage key changes, a job that still names the old
key is `superseded` with reason `input_version_changed`. It does not write
questions. A new job for the new key parses those bytes once.

Questions whose text is still in the new file keep their ids. Their file hash
and cells are updated. An approved answer on that id stays, including its text
and status. A question the new file dropped is removed when it has no approved
answer. A draft on that question is deleted with it: a draft can be generated
again, and the question is gone from the file. A question the new file dropped
that has an approved answer is kept. Its `source_location` becomes
`not_in_current_file`, and its sheet and cells are cleared. The approval stays
on that answer row. `mapping_version` stays non-negative because the existing
check constraint forbids a negative value, and this change adds no migration.
Export skips that marker. It does not write the question into the workbook, it
does not use the legacy column offset for it, and the old file hash does not
make `export_mapping_is_stale` true. The review page still shows the question
and its approved answer, labelled as not in the current file. A later delivery
of the same new bytes sees that survivor and does not insert the new questions
again.

## What the jobs page shows

`GET /api/jobs` and `GET /api/jobs/{id}` add `input_version_changed` and
`questionnaire_status`. The flag is true only when the job result reason is
`input_version_changed`. It is false on a parse of the current bytes. The
status is the questionnaire's current status when it is one of `uploaded`,
`parsed`, `failed`, `draft`, `completed`, `archived`, or `needs_review`. Any
other status is omitted.

The jobs page prints `input_version_changed. Questionnaire status: Parsed.`
when the flag is set and the status is known. When the flag is clear it prints
the status only, for example `Questionnaire status: Parsed.` Cancel and retry
do not change the questionnaire status or the question rows. The page shows
the job state (`Cancelled`, and Retry job for an admin) with that status.

A job for another workspace does not parse this questionnaire. The worker
rejects the workspace mismatch and inserts no questions.
