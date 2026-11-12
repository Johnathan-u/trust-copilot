# Notification rules and logs evidence

Status: the rules form now stores an active workspace member by user id. Editable templates stay deferred under the Coordinator ruling. Real-provider sandbox evidence stays blocked on owner accounts. Independent review of this follow-up is not claimed.

## UI and API contract

Code verified by CI: `6870007e0ba0ee5a4e448d270f73614464181b4a`. This note is the only later edit. Python 3.12.3, pytest 9.1.1, Node 24.22.1, Vitest 5.0.5, PostgreSQL 16.15, database `trustcopilot_test`. No provider network call.

Head `44b6ad30be3cdedb69fa3f6aff4fb1f27cfc2bcb` failed `build` on both events because the rules test wrote Next output to `.next-rules-acceptance`. The later web quality checks linted that generated code, and Next rewrote `tsconfig.json`. `web-release-e2e` passed on both events. The follow-up keeps the acceptance build inside `.next`, which ESLint and Prettier already ignore.

Exact-head CI of `6870007e0ba0ee5a4e448d270f73614464181b4a`:

| Event | Run | build | web-release-e2e |
|---|---|---|---|
| push | [43125311480](https://github.com/Johnathan-u/trust-copilot/actions/runs/43125311480) | job 130875767634, success | job 130875768510, success |
| pull_request | [43125318094](https://github.com/Johnathan-u/trust-copilot/actions/runs/43125318094) | job 130875790257, success | job 130875790623, success |

Both build logs: **6452 passed, 1 skipped, 52 warnings**. The only skip is `tests/test_trust_scoring_blind.py:33` (`external_data`: blind test pack not checked in). Push build took 924.83s. Pull request build took 726.49s. Both `web-release-e2e` jobs ended `playwright exit 0; axe check exit 0`.

Parent page, before the form change (`git show HEAD:apps/web/app/dashboard/notifications/page.tsx` at `8dc9a94cc30904c99407e56d1f23888103ef7774`):

`npx vitest run tests/unit/notification-rules-page.test.ts`

Exit 1. **3 failed.** Each failure still found the label `User email or ID`.

After the form change:

`npx vitest run lib/notification-rule-form.test.ts tests/unit/notification-rules-page.test.ts`

Exit 0. **5 passed** (2 helper cases, 3 page cases). The page case submits user id `17`, not membership id `90`, and a 422 `detail` list renders the fixed string.

`npx vitest run` from `apps/web`: exit 0. **57 files, 479 passed.**

PostgreSQL qualification, from `apps/api`:

```
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test \
  TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1 PYTHONPATH=. \
  python -m pytest tests/release/test_notification_rules_browser.py -vv --tb=short
```

Exit 0. **1 passed in 17.07s.** The admin created a `member.joined` rule for the editor's user id, disabled it, and re-enabled it. The delivery log row stayed `failed` / `dead-lettered` / `delivered_to_provider` false / `provider_mode` fixture. API process pids were 7540 then 7748; web pids were 7541 then 7749. After the restart the same `notification_policies` and `notification_log` rows were still there, and the editor saw no Add rule, Disable, Enable, Remove, Alert Rules, Recent Activity, or Delivery attempts controls. Policies and the log returned 403 for that editor.

`python -m pytest tests/release/test_domain_notifications.py -q` with the same database flags: exit 0. **53 passed.** This file was not changed.

Screenshots and axe, from `apps/web`:

```
npx playwright test --config=playwright.rules-evidence.config.ts --retries=0
```

Exit 0. **3 passed.** `axe-rules-form-360.json`, `axe-rules-form-768.json`, and `axe-rules-form-1440.json` each have `violationCount` 0. Screenshots are `screenshots/rules-form-360.png`, `rules-form-768.png`, and `rules-form-1440.png`.

`python scripts/security/secret_inventory.py paths` on the changed source and this evidence directory: **block 0**.

The new browser test is collected by the existing `pytest -rs` step and uses the Chromium install already in the build job. No workflow, candidate list, or evidence-checker edit is required for it to run. #230's pytest total was 6451 passed and 1 skipped. This branch adds one test. The CI totals above are 6452 passed and 1 skipped. The local qualification was re-run after the dist-directory fix: **1 passed in 16.13s**, and `tsconfig.json` was not rewritten.

## Still open

- Real Slack and SMTP/Gmail sandbox evidence (DoD6) needs owner accounts. It is not claimed.
- Editable templates remain follow-up TC-19-009a under [issue #85 comment 6503678126](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6503678126).
- Independent review of this follow-up has not been done.
- Optional CI retention, not applied here: upload `apps/web/playwright-report/rules-restart/` and `apps/web/test-results/rules-restart/` the same way the inbox restart report is uploaded.

## Earlier API qualification

Status at the earlier code SHA: tested code had all four required CI checks green and independent review had no remaining blocker. Coordinator review remained pending.

## Before the fix

Tested regression SHA: `e54d3cf52a27d6842137375ded15d9c90e9f64c9`.

[PR CI run 40921637032](https://github.com/Johnathan-u/trust-copilot/actions/runs/40921637032), build job 123616134095: **10 failed, 3206 passed, 1 external-data skip**. Intended failures were active user recipient validation (three), workspace role validation (two), prospective PATCH validation, obsolete recipient clearing, removed/demoted membership (two), and foreign in-app reference suppression. No fixture/setup/cleanup failures. Web release checks passed. This is RED regression evidence, not acceptance.

Eight additional schema tests rejected neither control characters, oversized fields nor lowercasing expansion before the fix: **8 failed**. After bounded input validation: **8 passed**.

## Current local checks

Python 3.12 and exact hashed requirements-dev.lock. Offline test safety guard enabled, proxy environment variables cleared. No local PostgreSQL service.

Exact local SHA `2be52ef8742c229bb8bcec5009c89c66f2e6a28d`: `PYTHONPATH=. python -m pytest tests/release/test_domain_notifications.py tests/release/test_safe_collection.py -k 'schemas or static_renderer or no_checked_in_credentials' -q`: **13 passed, 68 deselected**, exit 0. This includes 11 pure domain checks and two credential scans. The deselected cases are not local passes. Ruff check and format pass on changed Python files.

Review found that validating unchanged stale recipients prevented disabling an existing policy. Three regressions were published before the correction. At exact `2be52ef8742c229bb8bcec5009c89c66f2e6a28d`, [CI run40925620616](https://github.com/Johnathan-u/trust-copilot/actions/runs/40925620616), build job123630202584 returned **3 failed, 3254 passed, 1 external-data skip**. All original 49 domain cases passed; only removed/suspended user and deleted-role disable cases failed. No setup/cleanup failure. The earlier `8ff12a7` run stopped at the safety scan because a synthetic fixture lacked the required `test` marker; the fixture was explicitly renamed and safety scans passed.

The correction permits disable-only PATCH to retain stale routing while disabling delivery. Explicit routing edits and re-enable requests still validate the complete recipient. Current master `d9ab8b6` is included via a pure merge. The corrected code SHA is `d633d65e10cba6a01f9fcf975cbc38388e721913`. Both [PR CI run40929316021](https://github.com/Johnathan-u/trust-copilot/actions/runs/40929316021) and [push CI run40929305777](https://github.com/Johnathan-u/trust-copilot/actions/runs/40929305777) completed successfully: build and web-release-e2e passed in each, all four checks green. Push build job123643167492 recorded **3262 passed, 1 skipped**, with the skip solely the external blind-data pack. All 52 domain cases passed within that full PostgreSQL suite. Safe collection separately passed 29 checks; the existing CI API contract selection passed 20.

Exact-code local recheck at `d633d65e10cba6a01f9fcf975cbc38388e721913`: schema/template/credential selection **13 passed, 68 deselected**, plus published OpenAPI tests **5 passed**. Raw local outputs are in `pytest-local.txt`. No local PostgreSQL pass is claimed.

Independent reviewer rechecked the disable-only correction: no remaining blocking findings. Current membership/custom-role resolution, workspace recipient validation, bounded fields, foreign log joins, persisted provider-result/retry/dedupe, and cleanup were included in the review. Remaining limits are explicit below. This artifact records tested code; final evidence-only head/CI are recorded in the coordination thread to avoid a self-referential commit hash.

The domain module exercises 52 cases (11 pure checks and 41 PostgreSQL cases). Database teardown removes every added row and asserts original key sets and counts; read-only GET qualification compares complete row values. Synthetic provider outcomes qualify result propagation, retry and persisted dedupe, not real-provider sandbox delivery. No schema migration or shared dispatcher modification.
