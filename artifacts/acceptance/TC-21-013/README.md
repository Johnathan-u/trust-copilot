# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no migration. After merging master `bff2c39`, `alembic heads` is the single head `tc21006_gap_evaluation`. The merge tree matches `git merge-tree --write-tree`.

## Commands

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py tests/release/test_domain_compliance_gaps.py tests/release/test_domain_compliance_coverage.py tests/release/test_domain_compliance_mappings.py -q
```

Working directory `apps/web`. Node 24.

```text
npm run test:unit -- lib/evidenceGapConsumer.test.ts lib/coverageConsumer.test.ts
npm run typecheck
```

## SHA

Tests ran on `bad8783ee5eac85f147b02bef98a8d2891a252ab`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
|---|---|---|
| The four release files above | 0 | 30 passed, 378 warnings, 14.78s |
| `npm run test:unit -- lib/evidenceGapConsumer.test.ts lib/coverageConsumer.test.ts` | 0 | 7 passed |
| `npm run typecheck` | 0 | types generated, `tsc --noEmit` clean |

Pytest did not report a skipped test. The quiet progress line was thirty dots.
