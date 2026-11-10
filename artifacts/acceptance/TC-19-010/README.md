# TC-19-010 PostgreSQL and restart evidence

This directory records commands and outcomes. It does not accept the ticket. Independent review of the restart acceptance is still pending.

## Current CI pass

Head `78b3a32bf823e148ce491f9e687d71a81890ace6`. Command `pytest -rs` inside the CI `build` job (`apps/api`, step `Run backend tests`). Exit status 0. Python from the log is 3.11.18 (`Python 3.11.18` and `platform linux -- Python 3.11.18, pytest-9.1.1`). The log's PostgreSQL image is `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. The log does not print `SELECT version()`. The workflow comment on that digest names PostgreSQL 16.15 and pgvector 0.8.7.

Session totals on both build logs: 6425 passed, 0 failed, 1 skipped, 52 warnings. The skip is `tests/test_trust_scoring_blind.py:33`. It is outside the inbox module.

`tests/release/test_domain_in_app_notifications.py` passed every collected test and skipped 0. Both build logs show 35 dots and no skip or fail glyph:

```text
tests/release/test_domain_in_app_notifications.py ...................... [ 44%]
.............                                                            [ 44%]
```

The 35 collected tests include `test_inbox_ui_api_and_database_agree_after_full_process_restart`.

| Event | Run | Build job | web-release-e2e job | pytest summary |
| --- | --- | --- | --- | --- |
| push | [42912599974](https://github.com/Johnathan-u/trust-copilot/actions/runs/42912599974) | 130166820305 | 130166819629 | 6425 passed, 1 skipped, 52 warnings in 760.25s |
| pull_request | [42912630298](https://github.com/Johnathan-u/trust-copilot/actions/runs/42912630298) | 130166923805 | 130166923273 | 6425 passed, 1 skipped, 52 warnings in 820.57s |

Both `build` and `web-release-e2e` concluded success on each event. `restart_acceptance_followup.status` in `verification.json` is `CI_PASSED_PENDING_INDEPENDENT_REVIEW`.

## Restart report artifact

Each build job uploaded `inbox-restart-acceptance`.

- Push artifact [13808528138](https://github.com/Johnathan-u/trust-copilot/actions/runs/42912599974/artifacts/13808528138)
- Pull request artifact [13808743140](https://github.com/Johnathan-u/trust-copilot/actions/runs/42912630298/artifacts/13808743140)

Each archive contains the before and after Playwright HTML reports, `test-results/inbox-restart/before.json`, `test-results/inbox-restart/after.json`, and `test-results/inbox-restart/processes.json`. Both phases report expected 1, skipped 0, unexpected 0, and flaky 0. The after phase uses different API and web process ids from the before phase.

## Historical RED runs

The two earlier PostgreSQL runs stay in `verification.json` and are labeled `historical`.

- `f88e4ebd6f9354260b7bde94b036c94f0fc40e75`, run `40925575446`, build job `123630050157`: `pytest -rs` exited 1.
- `98e8781c749e0c9bffc11dd5a8d2767f656c053b`, run `40929390488`, build job `123643467469`: `pytest -rs` exited 1.

## Real-provider sandbox

Real-provider sandbox evidence awaits a coordinator ruling on [#85](https://github.com/Johnathan-u/trust-copilot/issues/85): either the item is N/A for the in-app inbox, or owner sandbox accounts are needed. This note does not decide that question.

The commit that adds these run ids is later than `78b3a32`. It does not change product code or tests.
