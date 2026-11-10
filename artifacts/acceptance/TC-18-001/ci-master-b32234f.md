# TC-18-001: release test run at the accepted commit

This file records `tests/release/test_domain_trust_requests.py` at the commit where TC-18-001 is accepted. The coordinator wrote it from the CI job log, and it is kept here because GitHub deletes CI logs after their retention period.

## Commit and run

- Commit: `b32234f7c07ffdd9e80949d228f3a92112cf2e5e`. This is master, the squash merge of #203 (head `fa743c0`), and its tree is identical to that head.
- Run: CI push run [42844125902](https://github.com/Johnathan-u/trust-copilot/actions/runs/42844125902).
  - `build` job [129926887146](https://github.com/Johnathan-u/trust-copilot/actions/runs/42844125902/job/129926887146): 2026-11-10T15:25:18Z to 15:42:19Z, `success`.
  - `web-release-e2e` job 129926886571: `success`. `screen-trust-requests.spec.ts` had 32 passed, including "public intake keeps one key" and "saved assignee is shown read-only".

## Command

From `apps/api`, with `SESSION_SECRET=test-secret`, `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`:

```
pytest -rs
```

The full suite covers the ticket's test file.

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Python 3.11.18, pytest 9.1.1; dependencies from `apps/api/requirements-dev.lock`
- PostgreSQL: `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`, with a database per run

## Totals

- Full backend suite: 6419 passed, 0 failed, 1 skipped, exit status 0 (766 s). The skip is `tests/test_trust_scoring_blind.py:33` (external data: blind test pack not checked in), which is unrelated to this ticket.
- `tests/release/test_domain_trust_requests.py`: 89 passed.
- Web unit tests: 49 files, 451 passed, including `tests/unit/public-trust-intake.test.ts` (5).

## Not covered

- No single test runs the real path from browser to Next to API to database for an intake retry.
- The retry key doesn't survive a page reload.
- There is no concurrent same-key test on the intake route.

All three are in follow-up TC-18-001a.
