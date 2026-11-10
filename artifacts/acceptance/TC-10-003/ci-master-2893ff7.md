# TC-10-003: release test run at the accepted commit

This file records `tests/release/test_job_idempotency.py` at the commit where TC-10-003 is accepted. That commit is the first with both #202 and the gap fixes from #204 (TC-10-003f). The coordinator wrote the record from the CI job log, and it is kept here because GitHub deletes CI logs after their retention period. The other files in this folder and in `../TC-10-003f/` record the worker's local runs.

## Commit and run

- Commit: `2893ff7db71340b7a98a8e3edbdf18f6e12e282f` (master, the squash merge of #204, head `c1c4f22`). It contains #202, merged as `a2b39c8`.
- Run: CI push run [42838058479](https://github.com/Johnathan-u/trust-copilot/actions/runs/42838058479).
  - `build` job [129905469059](https://github.com/Johnathan-u/trust-copilot/actions/runs/42838058479/job/129905469059): 2026-11-10T14:49:47Z to 15:09:19Z, `success`.
  - `web-release-e2e` job 129905468610: `success`.

## Command

From `apps/api`, with `SESSION_SECRET=test-secret`, `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`:

```
pytest -rs
```

The full suite covers the ticket's command `python -m pytest tests/release/test_job_idempotency.py -q`.

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Python 3.11.18, pytest 9.1.1; dependencies from `apps/api/requirements-dev.lock`
- PostgreSQL: `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`, with a database per run

## Totals

- Full backend suite: 6415 passed, 0 failed, 1 skipped, exit status 0 (776 s). The skip is `tests/test_trust_scoring_blind.py:33` (external data: blind test pack not checked in), which is unrelated to this ticket.
- `tests/release/test_job_idempotency.py`: 57 passed.
- Related files in the same run:
  - `test_answer_routing.py`: 134
  - `test_answer_sweep_direct_evidence.py`: 6
  - `test_authorization_answer_mutations.py`: 182
- Web unit tests: 48 files, 446 passed.

## Not covered

- The parse and index `FOR UPDATE` paths have no barrier-thread test.
- There is no unique index on `answers.question_id`. Writers are serialized by per-question advisory locks instead.
- The routes have no lock timeout, and approve has no version check.

All three are follow-up TC-10-003h.
