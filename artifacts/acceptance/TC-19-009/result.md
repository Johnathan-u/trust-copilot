# Notification rules and logs evidence

Status: implementation awaits exact-head PostgreSQL CI and independent review.

## Before the fix

Tested regression SHA: `e54d3cf52a27d6842137375ded15d9c90e9f64c9`.

[PR CI run 40921637032](https://github.com/Johnathan-u/trust-copilot/actions/runs/40921637032), build job 123616134095: **10 failed, 3206 passed, 1 external-data skip**. Intended failures were active user recipient validation (three), workspace role validation (two), prospective PATCH validation, obsolete recipient clearing, removed/demoted membership (two), and foreign in-app reference suppression. No fixture/setup/cleanup failures. Web release checks passed. This is RED regression evidence, not acceptance.

Eight additional schema tests rejected neither control characters, oversized fields nor lowercasing expansion before the fix: **8 failed**. After bounded input validation: **8 passed**.

## Current local checks

Python 3.12 and exact hashed requirements-dev.lock. Offline test safety guard enabled, proxy environment variables cleared. No local PostgreSQL service.

`PYTHONPATH=. python -m pytest tests/release/test_domain_notifications.py -k 'schemas or static_renderer' -q`: **11 passed, 38 deselected**, exit 0. The deselected database cases are not passes. Ruff check and format pass on all changed Python files. Full updated CI, exact published code SHA, and independent review results will be added after publication.

The domain module exercises 49 cases. Database teardown removes every added row and asserts original key sets and counts; read-only GET qualification compares complete row values. Synthetic provider outcomes qualify result propagation, retry and persisted dedupe, not real-provider sandbox delivery. No schema migration or shared dispatcher modification.
