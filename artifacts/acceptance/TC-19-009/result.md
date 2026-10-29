# Notification rules and logs evidence

Status: implementation awaits exact-head PostgreSQL CI and independent review.

## Before the fix

Tested regression SHA: `e54d3cf52a27d6842137375ded15d9c90e9f64c9`.

[PR CI run 40921637032](https://github.com/Johnathan-u/trust-copilot/actions/runs/40921637032), build job 123616134095: **10 failed, 3206 passed, 1 external-data skip**. Intended failures were active user recipient validation (three), workspace role validation (two), prospective PATCH validation, obsolete recipient clearing, removed/demoted membership (two), and foreign in-app reference suppression. No fixture/setup/cleanup failures. Web release checks passed. This is RED regression evidence, not acceptance.

Eight additional schema tests rejected neither control characters, oversized fields nor lowercasing expansion before the fix: **8 failed**. After bounded input validation: **8 passed**.

## Current local checks

Python 3.12 and exact hashed requirements-dev.lock. Offline test safety guard enabled, proxy environment variables cleared. No local PostgreSQL service.

Exact local SHA `2be52ef8742c229bb8bcec5009c89c66f2e6a28d`: `PYTHONPATH=. python -m pytest tests/release/test_domain_notifications.py tests/release/test_safe_collection.py -k 'schemas or static_renderer or no_checked_in_credentials' -q`: **13 passed, 68 deselected**, exit 0. This includes 11 pure domain checks and two credential scans. The deselected cases are not local passes. Ruff check and format pass on changed Python files.

Review found that validating unchanged stale recipients prevented disabling an existing policy. Three regressions were published before the correction. At exact `2be52ef8742c229bb8bcec5009c89c66f2e6a28d`, [CI run40925620616](https://github.com/Johnathan-u/trust-copilot/actions/runs/40925620616), build job123630202584 returned **3 failed,3254 passed,1 external-data skip**. All original 49 domain cases passed; only removed/suspended user and deleted-role disable cases failed. No setup/cleanup failure. The earlier `8ff12a7` run stopped at the safety scan because a synthetic fixture lacked the required `test` marker; the fixture was explicitly renamed and safety scans passed.

The correction permits disable-only PATCH to retain stale routing while disabling delivery. Explicit routing edits and re-enable requests still validate the complete recipient. Current master `d9ab8b6` is included via a pure merge. The corrected final code SHA and CI will be recorded after publication; no readiness is claimed yet.

The domain module exercises 52 cases (11 pure checks and 41 PostgreSQL cases). Database teardown removes every added row and asserts original key sets and counts; read-only GET qualification compares complete row values. Synthetic provider outcomes qualify result propagation, retry and persisted dedupe, not real-provider sandbox delivery. No schema migration or shared dispatcher modification.
