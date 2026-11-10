# TC-21-002: release test run at the accepted commit

This file records `tests/release/test_domain_controls.py` at the commit where TC-21-002 and TC-21-003 are accepted together. Both are accepted at the same commit because TC-21-002's evidence gate on remediation links came in #198. The coordinator wrote this record from the CI job log. GitHub deletes CI logs after their retention period, so the record is also kept here. The other files in this folder record the worker's local runs.

## Commit and run

- Commit: `f79d674b8897c3f03f74182f816b91f0bc6765b1` (master). It contains #197 (reviewed head `420d8eb`, merged as `302c37a`).
- Run: CI push run [42837038839](https://github.com/Johnathan-u/trust-copilot/actions/runs/42837038839).
  - `build` job [129901897013](https://github.com/Johnathan-u/trust-copilot/actions/runs/42837038839/job/129901897013): 2026-11-10T14:43:52Z to 15:05:50Z, `success`.
  - `web-release-e2e` job 129901897424: `success`.

## Command

From `apps/api`, with `SESSION_SECRET=test-secret`, `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`:

```
pytest -rs
```

The full suite covers the ticket's command `python -m pytest tests/release/test_domain_controls.py -q`.

## Environment

- Runner image: GitHub-hosted `ubuntu-26.04`, version 20261101.186.1
- Python 3.11.18, pytest 9.1.1; dependencies from `apps/api/requirements-dev.lock`
- PostgreSQL: `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`, with a per-run database

## Totals

- Full backend suite: 6410 passed, 0 failed, 1 skipped, exit status 0 (866 s). The skip is `tests/test_trust_scoring_blind.py:33` (external data: blind test pack not checked in), which is unrelated to this ticket.
- `tests/release/test_domain_controls.py`: 15 passed.
- Related files in the same run:
  - `test_domain_controls.py`: 15
  - `test_domain_compliance_controls.py`: 25
  - `test_domain_controls_unique_key.py`: 3
  - `test_control_engine.py`: 9
  - `test_remediation_loop.py`: 8
- Web unit tests: 48 files, 446 passed.

## Not covered

- Concurrency (verify, unlink and remediation interleaving) is not tested with real threads, and the control row is not locked. Both are follow-up TC-21-003b.
- A verified control is not re-checked when evidence is rejected, expires, or loses its document, or when the retention job deletes it. This is also TC-21-003b.
