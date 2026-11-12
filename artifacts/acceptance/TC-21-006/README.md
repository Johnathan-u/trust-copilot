# TC-21-006: Explainable compliance gaps and review workflow

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text. Notification delivery was stubbed.

#78 (TC-02-BUG-018b) is not merged. Master is still `6a26d60e44433720cf329cba08a8f096cb22e682`, and its alembic head is `tc21005_mapping_version`. This branch does not widen `ck_evidence_gaps_close_reason`. Resolved control-check rows store `CONTROL_CHECK_CLOSE_REASON` (`evidence_sufficient`).

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q
```

## SHA

Tests ran on `a4501822706ef88d40e74c9c3b913e5e76753239`. That commit is the parent of this evidence commit. This file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- Alembic head after the test: `tc21006_gap_evaluation (head)`
- Migration parent: `tc21005_mapping_version`
- Master at the run: `6a26d60e44433720cf329cba08a8f096cb22e682`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q` | 0 | 8 passed, 56 warnings, 5.49s |

Pytest printed `8 passed, 56 warnings in 5.49s` and did not report a skipped test. The quiet progress line was `........`.

# Follow-up: applicability, cooldown persistence, gaps contract

No framework requirement text was added. Notification delivery in the new tests is the in-app admin row or a stub. Nothing was sent to Slack or email. No migration was added. Open rows for controls that become non-applicable stay open, so no close-reason value was added and nothing was backfilled.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The product fix was not in the tree. The new applicability, non-applicable close, and cooldown tests were. The two consumer tests were not in this run.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q --tb=line
```

Base `d0464193504fde8a656e616f158230cf9ddfedcb`. The failing assertions are the uncommitted tests on that base, before commit `836695366552d42012e1190c2b55271e18fd13cf`.

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15, database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- Alembic head: `tc17003_security_claims (head)`

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q --tb=line` | 1 | 2 failed, 12 passed, 95 warnings, 7.29s |

`test_non_applicable_control_is_not_closed_as_sufficient` failed: the open `control_check` row was `resolved` instead of `open`. `test_cooldown_persists_without_a_second_notification` failed: `persisted` was `2`, which counted the reviewer-decided row, instead of `1`. The four applicability tests passed in this run. Pytest did not report a skipped test. Log: `pytest-gap-rules-red.txt`.

## Green command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_gaps.py -q --tb=short
```

## SHA

Tests ran on `836695366552d42012e1190c2b55271e18fd13cf`. That commit is the parent of this evidence commit. This section was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3, pytest 9.1.1
- Node v24.22.1 on `PATH` for the web-reader checks (`node --version` starts with `v24.`)
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- Alembic head after the test: `tc17003_security_claims (head)`
- Master at the branch point: `d0464193504fde8a656e616f158230cf9ddfedcb`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_gaps.py -q --tb=short` | 0 | 16 passed, 107 warnings, 8.58s |

Pytest printed `16 passed, 107 warnings in 8.58s` and did not report a skipped test. The quiet progress line was sixteen dots. Log: `pytest-gap-rules-green.txt`.
