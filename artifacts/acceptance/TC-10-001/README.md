# TC-10-001 acceptance evidence

## Current run (heartbeat end-to-end and rollback runbook)

The behaviour on master was missing an end-to-end heartbeat check, and the rollback bullet described a one-step downgrade that is no longer one step. This run adds those. The sections below are the original local record. Their SHAs and totals are not this run.

Command, from `apps/api`:

```
python -m pytest tests/release/test_job_leases.py -q
```

| Run | SHA | Environment | Exit | Totals |
|---|---|---|---|---|
| Local | `4ad1853b8ae50e0e8534871e62e0c970a612d0b3` | Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, psycopg2 2.9.13, PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), pgvector 0.6.0, database `trustcopilot_test` on 127.0.0.1, Linux 6.12.113+. `python` here is the venv interpreter. The captured process also passed `--tb=line -p no:cacheprovider`, which does not add or skip tests. | 0 | 28 passed, 0 failed, 0 skipped, 32 warnings, 16.35s |

The 28 are the previous 26 plus `test_heartbeat_keeps_the_lease_during_long_work` and `test_long_work_without_a_heartbeat_loses_the_lease`. Neither skipped. The file slept about 12s inside those two tests (6.0s each) and finished in 16.35s with the rest of the module, including the migration round trip. Postgres was listening. These are not an allowed skip.

`test_heartbeat_keeps_the_lease_during_long_work` calls `_process_one_job` with `worker.lease_seconds` patched to 2 and `worker.lease_heartbeat_seconds` patched to 0.3. The handler sleeps 6s, three times the lease. The job ends `completed`, there is no `job.lease_lost` audit, and the committed `lease_expires_at` moved forward by at least 2s during the sleep. The env clamp would turn a 2s lease into 10s, so the test patches the names the worker calls.

`test_long_work_without_a_heartbeat_loses_the_lease` is the same run with `_start_job_lease_heartbeat` replaced by a no-op. The job stays `running`, the result is not committed, and one `job.lease_lost` audit is written. `_process_one_job` catches `LeaseLost` from the commit fence.

### Deleting the heartbeat start (not committed)

On this same tree, the call at `apps/api/app/worker.py:1399` was deleted and then restored. The deletion was not committed.

```
lease_heartbeat = _start_job_lease_heartbeat(leased_job_id, owner)
```

Command, from `apps/api`:

```
python -m pytest tests/release/test_job_leases.py::test_heartbeat_keeps_the_lease_during_long_work -q --tb=short
```

Exit 1. 1 failed, 1 warning, 6.60s. The failure is the expiry check, before the completion assert:

```
tests/release/test_job_leases.py:1052: in test_heartbeat_keeps_the_lease_during_long_work
    assert gap >= _E2E_LEASE_SECONDS, (earlier, later, gap)
E   AssertionError: (datetime.datetime(2026, 11, 10, 19, 45, 13, 660634), datetime.datetime(2026, 11, 10, 19, 45, 13, 660634), 0.0)
E   assert 0.0 >= 2
```

`lease_expires_at` was the same timestamp at both samples. With the line restored, that test passes in the 28 above.

### Why product code changed

The control stayed `completed` until the fence clock changed. `reconcile_previous_attempts` runs an `UPDATE` and, when it matches nothing, does not commit, so the job transaction stays open across the handler. `now()` is the start of that transaction. A 6s sleep still looked leased on a 2s expiry, with or without a heartbeat. `lease_is_held` now compares `lease_expires_at` to `statement_timestamp()`, the database clock at the check. Renewal still uses `now()` in the heartbeat's own short transaction. After that change the control loses the lease, and the deletion above fails the main test.

### Rollback count

On master `edd332013d09af4222b9c700a489f9b4c7709091` the alembic chain is linear, one head, `tc17003_security_claims`. Eight revisions sit above `tc10001_job_leases`. `alembic downgrade bug018c_one_open_gap` walks those eight and then this revision. The list and the safe lease-only rollback are in `docs/release/tickets/TC-10-001.md`.

## CI of `4ad1853`

This section records the GitHub Actions `CI` workflow for commit `4ad1853b8ae50e0e8534871e62e0c970a612d0b3`. The commit that adds this section is a later SHA, so it is not the SHA under test.

Both `build` and `web-release-e2e` succeeded on the push and on the pull request.

| Event | Run | Build job | web-release-e2e job |
|---|---|---|---|
| push | [42888689793](https://github.com/Johnathan-u/trust-copilot/actions/runs/42888689793) | 130083731126 | 130083730506 |
| pull_request | [42888729722](https://github.com/Johnathan-u/trust-copilot/actions/runs/42888729722) | 130083872306 | 130083871747 |

- Command: from `apps/api`, `pytest -rs`, with `SESSION_SECRET=test-secret`, `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`. That suite runs `tests/release/test_job_leases.py`.
- Environment: GitHub-hosted `ubuntu-26.04` image `20261101.186.1`; Python 3.11.18; pytest 9.1.1; SQLAlchemy 2.0.55; psycopg2-binary 2.9.13; pgvector 0.5.1. PostgreSQL image `pgvector/pgvector:pg16` digest `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. Push database `tc_ci_42888689793_1_test`. Pull-request database `tc_ci_42888729722_1_test`.
- Exit status: 0 on both build jobs.
- Totals for this file: 28 passed, 0 skipped. Both build logs show one progress line and no `s`:

  `tests/release/test_job_leases.py ............................            [ 54%]`

  That is 28 dots. The two new tests are in that line. Neither skipped.
- Full suite, both runs: 6423 passed, 1 skipped, 52 warnings. Push pytest duration 815.99s. Pull-request pytest duration 793.27s. The skip is `tests/test_trust_scoring_blind.py:33` (external data). It is not in `test_job_leases.py`.

`result.json` in this directory is the same record. Reviewer signoff is still pending. This record does not accept the ticket.

## Re-parent run

These commands ran on `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` (`d5dc642`), after merge `dc7979e` of `origin/master` `76ae791` and the re-parent of `tc10001_job_leases` onto `bug018c_one_open_gap`. This README commit does not change that code.

`alembic heads` printed exactly `tc10001_job_leases (head)`. The lease-file round trip downgrades to `bug018c_one_open_gap` and upgrades again. The sentinel job row is unchanged, and `ix_jobs_running_lease_expires_at` is present after the re-upgrade.

| What | Command | SHA | Exit | Totals |
|---|---|---|---|---|
| Lease tests, including the barrier race and the lost-lease worker tests | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py -q --tb=line -p no:cacheprovider` | `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` | 0 | **15 passed** |
| Safe collection | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_safe_collection.py -q --tb=line -p no:cacheprovider` | `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` | 0 | **29 passed** |
| Heads / migration | `pytest tests/release/test_cross_workspace_refs.py::test_trigger_revision_is_on_the_single_alembic_head_chain tests/release/test_provider_adapter.py::test_migration_columns_present tests/release/test_provider_adapter.py::test_migration_has_unique_descriptive_revision_after_075 tests/release/test_job_retries.py::test_migration_downgrade_and_upgrade_roundtrip -q --tb=line` | `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` | 0 | **4 passed** |
| Related job tests (retries, idempotency, TC-10-003d) | `pytest tests/release/test_job_retries.py tests/release/test_job_idempotency.py tests/release/test_auto_generate_enqueue_conflict.py -q --tb=line` | `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` | 1, then 0 | **121 passed, 1 failed**, then the one failure passed alone |
| Alembic heads | `cd apps/api && alembic heads` | `d5dc642c6a3e8ccba32461fb8e926f8f5b2df297` | 0 | `tc10001_job_leases (head)` |

The related-job failure was `test_replay_returns_same_error_body_as_live_response`: the live call returned 429 because workspace 1 had already used its 10 `ai_jobs` for that hour (`workspace_usage.count = 10`). Clearing that hour's counter and running the test alone: **1 passed**, exit 0. It is not a lease failure.

On `78dcb0e` (same lease code as `8a37e80`; that commit is docs only), the four tests added for the blockers were run against that implementation. `test_heartbeat_is_at_most_half_the_lease` failed (`lease_heartbeat_seconds()` was 40, not 30). `test_two_recoverers_take_one_expired_job`, `test_worker_loop_does_not_commit_after_the_lease_expires`, and `test_worker_loop_does_not_retry_after_a_lost_lease_exception` passed.

## Earlier run

Tests below ran on commit `533c5324eeddc5dcaed3ab922d961665642333d0` (`533c532`).
That commit is the re-parent of `tc10001_job_leases` onto `tc21006_gap_evaluation`, after merge commit `decef96` of `origin/master` `bff2c39`.
The evidence files in this directory were added after that run and do not change the code under test.

Base at push time: `bff2c39f5ebcf30926e7fad0b854fb5a56e70f0e` (`bff2c39`).
Alembic parent: `tc21006_gap_evaluation`. Single head after this branch: `tc10001_job_leases`.

## Environment

- Python 3.12.3, pytest 9.1.1, ruff 0.5.6
- SQLAlchemy 2.0.55, Alembic 1.20.1, FastAPI 0.162.0
- PostgreSQL 16.15, database `trustcopilot_test` on `127.0.0.1` (name ends in `_test`)
- Master regression used `trustcopilot_master_test` and `origin/master` `bff2c39`
- Synthetic rows only. No network calls from the tests, no real provider keys

## Commands, exit status, totals

| What | Command | SHA | Exit | Totals |
|---|---|---|---|---|
| Lease tests | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py -q --tb=no -p no:cacheprovider` | `533c5324eeddc5dcaed3ab922d961665642333d0` | 0 | **11 passed**, 5 warnings |
| Lease tests, safe collection, alembic head checks, TC-10-003d auto-generate | `cd apps/api && SESSION_SECRET=test-secret TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py tests/release/test_safe_collection.py tests/release/test_cross_workspace_refs.py::test_trigger_revision_is_on_the_single_alembic_head_chain tests/release/test_provider_adapter.py::test_migration_columns_present tests/release/test_provider_adapter.py::test_migration_has_unique_descriptive_revision_after_075 tests/release/test_job_retries.py::test_migration_downgrade_and_upgrade_roundtrip tests/release/test_auto_generate_enqueue_conflict.py -q --tb=short -p no:cacheprovider` | `533c5324eeddc5dcaed3ab922d961665642333d0` | 0 | **49 passed**, 13 warnings |
| Alembic heads | `cd apps/api && DATABASE_URL=.../trustcopilot_test TRUST_COPILOT_TESTING=1 python -m alembic heads` | `533c5324eeddc5dcaed3ab922d961665642333d0` | 0 | `tc10001_job_leases (head)` |
| Ruff | `cd apps/api && ruff check . && ruff format --check .` (0.5.6), then again on the merged worker | `533c532` | 0 | check passed; format check passed |
| Tests on master | `PYTHONPATH=<master worktree> TC_TEST_DATABASE_URL=.../trustcopilot_master_test pytest tests/release/test_job_leases.py -q --tb=line` against `bff2c39` | `bff2c39` | 2 | **1 collection error**. `ImportError: cannot import name 'LEASE_EXPIRED'`. **0 passed. All 11 tests fail before they run.** |

## What master did

On `bff2c39`, `jobs` still has no `lease_owner` or `lease_expires_at`. `worker.recover_abandoned_jobs` does not exist. A probe on the pre-lease claim loop (same `claim_job` body master still has) claimed one queued job, left it `running` at attempt 1, and a second `claim_job` returned nothing.

## Full-suite comparison before this merge

On implementation `ff0775a` against then-master `6a26d60`, two full `pytest -rs` runs were started together (separate `*_test` databases). By test id:

- Branch: 3142 passed, 4 failed, 11 skipped, exit 1
- Master: 3131 passed, 4 failed, 11 skipped, exit 1
- Only on the branch: the 11 `test_job_leases` tests, all passed
- Status changes for shared tests: 0

The four failures were the same test ids on both sides. Two are the known environmental ones: `test_ac3_schema_consumer_and_persisted_outcome_agree_across_retry` (typescript is not installed) and `test_routes_agree_on_canonical_contract_and_retry` (Node is v22, the test wants v24). The other two, `test_migration_fresh_install_upgrade_and_downgrade` and `test_migration_upgrades_and_downgrades_on_a_fresh_database`, failed while both suites were connected and **passed when re-run alone** (2 passed, exit 0).

## AC mapping

- AC1, two workers cannot own one valid lease, and the heartbeat continues during long work: `test_two_workers_cannot_own_the_same_lease`, `test_heartbeat_renews_only_for_the_current_owner`, `test_heartbeat_loop_keeps_renewing_until_stopped`, `test_heartbeat_loop_uses_injected_sleep_and_stops_when_renewal_fails`.
- AC2, a killed worker's lease expires and another worker resumes through the existing retry cap and idempotency ledger: `test_lost_lease_does_not_commit_the_result`, `test_expired_lease_is_recovered_without_running_the_side_effect_twice`, `test_attempt_cap_stops_an_abandoned_job`, `test_idempotency_owner_fence_still_holds_beside_a_job_lease`, `test_null_lease_on_a_running_job_is_not_recovered`.
- Migration round trip and the 32-character revision-id limit: `test_migration_upgrade_downgrade_upgrade_is_lossless`.
