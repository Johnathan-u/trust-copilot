# TC-21-007d: coverage reuses the TC-21-003 qualification rule

`compliance_coverage._evidence_is_current` now calls `evidence_qualification.evidence_qualifies` on every check. Coverage still returns its own reason codes: `qualifies`, `stale`, `deleted_document`, `not_approved`, and `missing`. A `qualifies` result requires the shared rule to agree. When the shared rule rejects an item that coverage's own codes would call `qualifies`, the result is `missing`, so coverage does not count it.

`docs/release/tickets/TC-21-007.md` records the two meanings of stale. Coverage stale means the evidence has expired. The control engine's stale means the evidence qualifies and is more than 180 days old. The checks stay different. Aligning them needs a product ticket, and this change does not open one.

This note does not accept TC-21-007 or TC-21-007d. No migration. The shared qualification function is unchanged. No route permission changed.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The new test was in the tree. The call to `evidence_qualifies` was not.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_tc21007d_qualification_rule.py::test_tc21007d_coverage_reuses_the_qualification_rule -q --tb=short
```

Base `6cdd70657dc562865a6c486307268047b8010be4`. The red run is the uncommitted test on that base, before the product change.

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- Alembic head: `tc04005a_member_revoked_at (head)`

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 1 failed, 10 warnings, 0.48s |

The failure is the missing `evidence_qualifies` binding on `compliance_coverage`. The case matrix had already agreed with the shared rule. Log: `failing-before.txt`.

## Green command

Same interpreter, database, and test. The call and the stale note are in the tree.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest tests/release/test_tc21007d_qualification_rule.py::test_tc21007d_coverage_reuses_the_qualification_rule -q --tb=short
```

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 1 passed, 10 warnings, 0.44s |
| `python -m pytest tests/release/test_tc21007d_qualification_rule.py tests/release/test_domain_compliance_coverage.py tests/test_compliance_coverage_unit.py tests/test_coverage_question_provenance.py -q --tb=line` | 0 | 49 passed, 118 warnings, 3.71s |
| `ruff check app/services/compliance_coverage.py tests/release/test_tc21007d_qualification_rule.py` | 0 | clean |
| `ruff format --check` on those two files | 0 | already formatted |

Pytest did not report a skipped test. Log: `passing-after.txt`.

## Scope

The change touches the coverage side of the evidence-qualification decision, so OD-15's pre-merge review still applies. It does not change authentication, authorization, admin controls, the CI workflow, or migrations.
