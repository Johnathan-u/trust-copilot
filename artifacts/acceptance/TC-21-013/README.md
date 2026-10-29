# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no new migration. After merging master `76ae791`, `alembic heads` is the single head `bug018c_one_open_gap`. The merge tree matches `git merge-tree --write-tree`.

Create locks `pg_advisory_xact_lock(150015, questionnaire_id)` and `pg_advisory_xact_lock(150016, control_id)`. A second open question gap hits `uq_evidence_gaps_one_open_per_question` and returns the existing row.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py tests/release/test_domain_compliance_gaps.py tests/release/test_domain_compliance_coverage.py tests/release/test_domain_compliance_mappings.py -q
```

## SHA

Tests ran on `29fd60eb72048c02dcf7cc3ee31f5f061dc22d67`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
|---|---|---|
| The four release files above | 0 | 36 passed, 434 warnings, 16.00s |

Pytest did not report a skipped test. The quiet progress line was thirty-six dots.
