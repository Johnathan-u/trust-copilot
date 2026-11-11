# TC-21-013: Evidence gap ownership and resolution

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Notification delivery was stubbed. There is no new migration. The pure merge of master `d9ab8b6` has tree equal to `git merge-tree --write-tree`. `alembic heads` is the single head `tc10001_job_leases`.

Create locks `pg_advisory_xact_lock(150015, questionnaire_id)` and `pg_advisory_xact_lock(150016, control_id)`. The scanner takes the same control lock before it inserts. A second open question gap hits `uq_evidence_gaps_one_open_per_question` and returns the existing row.

Decision and resolve use `UPDATE ... WHERE status = 'open' RETURNING`. The loser is 409, writes no audit row, and keeps no idempotency row. A decision that loses to resolve says `already resolved`.

A gap type longer than 64 characters, or a NUL byte in a string field, is 422. A create idempotency key stores `sha256` of the sorted JSON body in the existing payload. The same body replays. A different body is 422 and writes nothing.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release -q
```

## SHA

Tests ran on `94ab773f04b0be8ae66d73fa691ab13386f9d231`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `pytest tests/release -q` | 0 | 1816 passed, 7177 warnings, 182.55s |

Pytest did not report a skipped test.

## Question-gap refusal, 2026-11-11

The named file is `apps/api/tests/release/test_domain_evidence_gaps.py`. CI does not invoke that path alone. The `Run backend tests` step runs `pytest -rs` from `apps/api`, and that step executes the file. Exit 0 is the successful step: the job completed and the summary below is the pytest result.

SHA `8519c9ac38e7026f69fedf0e65cd8a11bed91c1f`. This section was added after that commit and does not change the tests.

### Environment (CI build log)

- Python 3.11.18 (`Backend tool versions`, and `platform linux -- Python 3.11.18, pytest-9.1.1, pluggy-1.7.0`)
- PostgreSQL 16.15 with pgvector 0.8.7. The log pulls `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. `.github/workflows/ci.yml` identifies that digest as PostgreSQL 16.15 and pgvector 0.8.7. The log does not print `SELECT version()`.
- Host `127.0.0.1:5432`. `pg_isready` printed `127.0.0.1:5432 - accepting connections`. User `tc_ci`.
- Push database `tc_ci_43010768523_1_test`. Pull-request database `tc_ci_43010799033_1_test`.

### File and suite

```text
tests/release/test_domain_evidence_gaps.py ..................            [ 44%]
```

Eighteen dots and no skip marker: 18 passed in that file. The same line is in both build logs.

| Event | Run | `build` | `web-release-e2e` | Suite | Exit |
| --- | --- | --- | --- | --- | --- |
| push | [43010768523](https://github.com/Johnathan-u/trust-copilot/actions/runs/43010768523) | success | success | 6442 passed, 1 skipped, 52 warnings, 758.97s | 0 |
| pull_request | [43010799033](https://github.com/Johnathan-u/trust-copilot/actions/runs/43010799033) | success | success | 6442 passed, 1 skipped, 52 warnings, 856.89s | 0 |

The only skip is `tests/test_trust_scoring_blind.py:33` (`external_data: blind test pack not checked in`). Master before this branch was 6441 passed, 1 skipped. This branch adds one test.

## Evidence commit `78cf12a`

`78cf12a0a833a0a1fa846e0f353e10c7ed5ab811` only appends the section above. The test file is unchanged.

Push run [43013750669](https://github.com/Johnathan-u/trust-copilot/actions/runs/43013750669): `build` success, `web-release-e2e` success. Python 3.11.18, pytest 9.1.1. Database `tc_ci_43013750669_1_test` at `127.0.0.1:5432` (`pg_isready`: `127.0.0.1:5432 - accepting connections`). The file line is 18 dots. Suite exit 0: `6442 passed, 1 skipped, 52 warnings in 842.77s`. The only skip is `tests/test_trust_scoring_blind.py:33`.

Pull-request run [43013757129](https://github.com/Johnathan-u/trust-copilot/actions/runs/43013757129): `web-release-e2e` success, `build` failure. The suite was `1 failed, 6441 passed, 1 skipped, 52 warnings in 618.33s`. The failure is `tests/release/test_job_leases.py:1052` in `test_heartbeat_keeps_the_lease_during_long_work`: the two `lease_expires_at` samples were the same timestamp and the gap was `0.0`, which is below `_E2E_LEASE_SECONDS` (2). That test is outside this ticket. The same tree passed it on the push run.
