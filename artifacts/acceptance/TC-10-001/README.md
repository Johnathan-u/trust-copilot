# TC-10-001 acceptance evidence

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
