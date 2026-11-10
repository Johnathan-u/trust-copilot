# TC-04-001: release test run at the accepted commit

This file records the `test_registration.py` run at the commit where TC-04-001 is accepted. The coordinator wrote it from the CI job log. GitHub deletes CI logs after their retention period, so the record is also kept here. `result.json` and `pytest-q.txt` in this folder record the worker's local run, on the tree committed in #193's head `138e047`.

## Commit and run

- Commit: `ea87cb7418f569d674d2ca0fcf5da0fb3598fd14` (master, the squash merge of #193; reviewed head `138e047`).
- Run: CI push run [42794791965](https://github.com/Johnathan-u/trust-copilot/actions/runs/42794791965).
  - `build` job [129757057421](https://github.com/Johnathan-u/trust-copilot/actions/runs/42794791965/job/129757057421): ran 2026-11-10T09:55:45Z to 10:09:26Z, conclusion `success`.
  - `web-release-e2e` job 129757057880: also `success`.
- Before the merge, head `138e047` was green on push run 42721446209 and pull_request run 42721454321.

## Command

From `apps/api`, with `SESSION_SECRET=test-secret`, `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`:

```
pytest -rs
```

`tests/release/test_registration.py` runs as part of the full suite. It is the ticket's `python -m pytest tests/release/test_registration.py -q`, run with every other test.

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Python 3.11.18
- Dependencies from `apps/api/requirements-dev.lock`
- PostgreSQL: `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`, with a per-run database
- Web unit tests (vitest) in the same job

## Totals

- Full backend suite: 6384 passed, 0 failed, 1 skipped, exit status 0 (601 s). The skip is `tests/test_trust_scoring_blind.py:33` (external data: the blind test pack is not checked in), which is unrelated to this ticket.
- `tests/release/test_registration.py`: 52 passed.
- `tests/test_security_remediation.py`: 36 passed.
- Web unit tests: 48 files, 446 passed.

## Not covered

- No live identity provider was called. Provider flows use mocked token exchanges and signed test tokens.
- `email-verification.spec.ts` (4 passed in `web-release-e2e`) mocks every API route. The real path, from mailed link to page to API, has not been exercised end to end.
