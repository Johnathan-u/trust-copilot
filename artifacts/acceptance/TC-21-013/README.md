# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no migration. `alembic heads` is the single head `tc21006_gap_evaluation`.

`POST /api/compliance/controls/{control_id}/verify` uses `require_can_review`. Resolve uses that dependency. Decision uses `require_can_admin` because verify's dependency is below admin.

Master's `ck_evidence_gaps_close_reason` allows NULL, `question_removed`, `answer_sufficient`, and `evidence_sufficient`. Question resolves use `answer_sufficient`. Control-check resolves use `evidence_sufficient`.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py -q
```

## SHA

Tests ran on `5a9b46bd86a529248fa5c220bef1ffcd2c6a88ff`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_evidence_gaps.py -q` | 0 | 13 passed, 118 warnings, 4.69s |
| `npm run test:unit -- lib/evidenceGapConsumer.test.ts` | 0 | 3 passed |
| `npm run typecheck` | 0 | types generated, `tsc --noEmit` clean |

Pytest did not report a skipped test. The quiet progress line was `.............`.
