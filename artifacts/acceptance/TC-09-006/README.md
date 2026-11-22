# TC-09-006 questionnaire replay

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-09-006.md`. The runbook is `docs/ops/questionnaire-replay.md`. This folder does not edit the tracker and does not record CI run ids.

The earlier `pytest.txt`, `pytest-hashes.txt`, `pytest-replay.txt`, and `ci-runs.md` are the PARTIAL verification logs. They are unchanged.

## Command

From `apps/api`:

```sh
python -m pytest tests/release/test_questionnaire_replay.py -q
```

The tests build synthetic workbooks in the process. They do not read a customer file. With `TC_REQUIRE_DB=1` a missing database fails the run instead of skipping. This run used that setting. Nothing was skipped.

## Failing before

Product code was master `0e4969fce820db8a5072a2e815e72edda1a45802`. The new test ran against that code. Log: `failing-before.txt`.

Exit 1. 6 failed, 1 passed, 0 skipped. The history response had no `input_version_changed` or `questionnaire_status`. A replaced file left the old `original_file_hash` on the kept question. Two deliveries of the same job hit the existing `job_effects` unique key. The cross-workspace case passed.

## Passing after

Same command on product code `4bd721d1a280ef26d74f01962e2694d731c9d504`. Log: `passing-after.txt`.

8 passed, 0 failed, 0 skipped, exit 0. Pytest also printed warnings from `datetime.utcnow` in existing models. The same bytes do not duplicate questions. A replaced file is parsed once. An approved answer stays. A dropped approved question is marked `not_in_current_file` and the real export of the new file succeeds. The dropped approval is not written into the workbook and remains on the answer row. A genuinely stale mapping is still rejected. A draft on a dropped question is removed. `input_version_changed` is set on the stale job and clear on the new parse. Workspace 2 is untouched by a workspace 1 job. Cancel and retry leave the questionnaire parsed. Two concurrent deliveries insert one set of questions.

From `apps/web`, `npx vitest run tests/unit/job-history-consumer.test.ts` was 1 failed and 17 passed before `inputVersionNotice` existed, and 18 passed after. `npx playwright test e2e/release/screen-jobs.spec.ts --grep input_version_changed` passed 1 test. The page shows `input_version_changed. Questionnaire status: Parsed.`

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, openpyxl 3.1.5, python-docx 1.2.0, pypdf 6.21.3, PostgreSQL 16.15, pgvector 0.6.0. Node 24.22.3, Vitest 5.0.5. Fixtures are synthetic. No customer workbook. No new migration.
