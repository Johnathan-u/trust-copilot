# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no migration. `alembic heads` is the single head `tc21006_gap_evaluation`.

`POST /api/compliance/controls/{control_id}/verify` uses `require_can_review`. That permission is below admin, so decision and resolve use `require_can_admin`. List, read, and create stay on review. The permission change is a separate commit after the reviewed `6f504c2`.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py -q
```

## SHA

Tests ran on `3355cfae0ab2a595a1d554b45a09972d898ab7fb`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_evidence_gaps.py -q` | 0 | 8 passed, 73 warnings, 3.63s |

Pytest did not report a skipped test. The quiet progress line was `........`.
