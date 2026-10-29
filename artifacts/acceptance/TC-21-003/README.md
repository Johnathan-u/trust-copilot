# TC-21-003: Control library lifecycle and evidence verification

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework control text.

| AC | Result |
|---|---|
| AC1 Qualifying evidence and unique control-evidence pairs | Met by `apps/api/tests/release/test_domain_compliance_controls.py`. Pending, expired, and deleted-document evidence do not verify a control. A second link of the same pair is not inserted. |
| AC2 Permissions, foreign references, and partial failure on PostgreSQL | Met by the same file. Anonymous, reviewer, and editor denials match the existing gates. Another workspace is 404. A failed accept commit leaves no evidence item and no link. |
| AC3 Schema, persisted outcome, and retry | The response fields are unchanged. A second verify keeps `verified_at`. A second link returns the same id. No web module types these routes. |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_controls.py -q
```

## SHA

Tests ran on `4b4da1d2419616e36750901152150467fea4f89a`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21003_evidence_link_uniq`, parent `tc21002a_canonical_uniq`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_controls.py -q` | 0 | 5 passed, 0 skipped, 68 warnings, 7.23s |

No test in that file was skipped.
