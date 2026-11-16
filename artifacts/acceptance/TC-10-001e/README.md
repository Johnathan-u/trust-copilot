# TC-10-001e acceptance evidence

The heartbeat check in `test_heartbeat_keeps_the_lease_during_long_work` used to read `lease_expires_at` once after a fixed sleep and require the two timestamps to differ by at least `_E2E_LEASE_SECONDS` (2). A read taken before the heartbeat commit is visible sees the same timestamp twice. Pytest reports that as `assert 0.0 >= 2`. The lease renewal is fine. The assertion now polls the committed timestamp on a 0.05s sleep until the delta reaches 2 seconds or the deadline passes. The deadline is the existing 6s long-work window plus a 1s grace. The handler still occupies the full 6s, so the job still runs three times the 2s lease. A delta below 2 fails, and the message includes the last observed delta. The test is not retried, skipped, or marked xfail.

## Race before the poll

`race-before.txt`. A real `renew_lease` on PostgreSQL was held until after one later sample of the claim timestamp. That single sample is the old assertion, taken too early:

```
gap=0.0
AssertionError:
assert 0.0 >= 2
```

The same baseline was then polled with `_poll_committed_expiry` and the same threshold. The held renewal was released. Eight heartbeats committed. The poll returned as soon as the delta reached 2 seconds. It did not pass on a smaller move.

```
polled_gap=2.206279
elapsed_s=2.157
heartbeat_beats=8 lost=False
assert 2.206279 >= 2 passed
```

Python 3.12.3, pytest 9.1.1, PostgreSQL 16.15, database `trustcopilot_test`, 2026-11-16T12:46:34Z.

## Polled test, 50 consecutive runs

`poll-50.txt`. Command, from `apps/api`:

```
TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py::test_heartbeat_keeps_the_lease_during_long_work -q --tb=line -p no:cacheprovider
```

50/50 passed. Each run is a separate pytest process. The last run reports `1 passed, 1 warning in 6.55s`. Exit 0. Same interpreter and database as the race log. Started 2026-11-16T12:38:55Z.

## Full module

`module.txt`. Command, from `apps/api`:

```
TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py -q --tb=line -p no:cacheprovider
```

31 passed, 0 failed, 0 skipped, 38 warnings, 20.46s. Exit 0. 2026-11-16T12:46:37Z.

CI run ids for `build` and `web-release-e2e` on push and pull_request are in the pull request body, for the final head. This file does not accept TC-10-001 or TC-10-001e.
