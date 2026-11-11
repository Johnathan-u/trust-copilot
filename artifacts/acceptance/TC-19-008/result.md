# TC-19-008 acceptance evidence

Real Slack, Gmail, and SMTP qualification is **BLOCKED**. No mailbox, Slack workspace, token, or outbound notification call was used. Email uses the console provider. Slack uses the labelled development stub.

## Environment

- Python 3.12.3 locally (`/tmp/tc-venv/bin/python`). GitHub CI uses Python 3.11.
- pytest 9.1.1, ruff 0.5.6, SQLAlchemy 2.0.55, psycopg2 2.9.13
- Local PostgreSQL 16 with the `vector` extension, database `trustcopilot_tc19008_suite_test`
- Master pins `sqlalchemy>=2.0,<2.1`. psycopg v3 was not added.
- `alembic heads`: `tc19008_notification_delivery (head)`. Parent revision is `tc10003b_idempotency_owner_token`, master's head after #43.

## Release tests

Command, from `apps/api`:

```bash
TC_REQUIRE_DB=1 SESSION_SECRET=test-secret /tmp/tc-venv/bin/python -m pytest tests/release/test_notification_delivery.py -q --tb=line -p no:warnings
```

Exit status: **0**

Totals: **22 passed**, 0 failed, 0 skipped. The file covers distinct event ids, a missing event id, a 15-minute lease and the 24-hour extension, a Slack write failure after acceptance, an in-app claim that rolls back with the caller, genuine repeats for role changes and generation jobs, the compliance cooldown (one job fires once, a new job inside 30 minutes is suppressed, a new job after the cooldown fires), two sessions racing one key, worker prune, and a fresh-database upgrade. `alembic_version.version_num` stays varchar(32). The migration check walks descendants and downgrades to the parent stored on the revision.

That file includes a fresh-database upgrade to `tc19008_notification_delivery`, downgrade to the parent recorded on the revision (`tc10003b_idempotency_owner_token`), and upgrade again. The side database name ends in `_test` and is created with the same role as `TC_TEST_DATABASE_URL` or `DATABASE_URL`.

## Existing notification, in-app, Slack, and Gmail tests

Command, from `apps/api`, run before the migration case was added (9 of the 10 release tests, plus the existing suites):

```bash
TC_REQUIRE_DB=1 SESSION_SECRET=test-secret /tmp/tc-venv/bin/python -m pytest \
  tests/release/test_notification_delivery.py \
  tests/release/test_message_provider_wiring.py \
  tests/test_phase_c_notifications.py \
  tests/test_phase_d_slack.py \
  tests/test_phase_e_slack_ingest.py \
  tests/test_phase_f_gmail.py \
  tests/test_notification_fire_points.py \
  tests/test_in_app_notifications.py \
  -q --tb=line -p no:warnings
```

Exit status: **0**

Totals: **158 passed**, 0 failed, 0 skipped.

The same command after the migration case is included in the full suite below.

## CI-equivalent suite

```bash
pre-commit run --all-files
```

Exit status: **0** (ruff 0.5.6, ruff-format, prettier, trailing whitespace, end of file, yaml).

```bash
cd apps/api && alembic heads
```

Output: `tc19008_notification_delivery (head)`.

```bash
cd apps/api && TC_REQUIRE_DB=1 SESSION_SECRET=test-secret /tmp/tc-venv/bin/python -m pytest -rs -q --tb=line -p no:warnings
```

Exit status: **0**

Totals: **1713 passed**, 2 skipped, 0 failed, after merging master `e86812b`. Database: `trustcopilot_tc19008_suite_test`.

Skips: blind pack not found, no reviewed workspace controls.

`tests/release/test_safe_collection.py`: **26 passed**.

This revision does not change `apps/web`. The previous `npm run build` (35 pages) was not repeated.

## Browser

Signed in as `demo@trust.local` on `http://127.0.0.1:3000/dashboard/notifications`. Email and Slack started checked. In-app started unchecked, stayed checked after a reload when enabled, and stayed unchecked after it was turned off again. The activity log showed a dev-stub send as not delivered to the provider.

## Not in this run

`tests/test_alerts_api.py` and `tests/test_coverage_api.py` are not in the test tree on this branch (they were moved out of `tests/` on master). They were not run.

## Delivery-attempt visibility

Appended for the admin delivery-attempt list, the notifications screen spec, and the doc refresh. Earlier sections above are unchanged.

Real Slack, Gmail, and SMTP qualification stays **BLOCKED**. No sandbox account was used and no real provider was called.

Local environment:

- Node v24.22.1 (`.nvmrc` is 24.22.1). Python 3.12.3, pytest 9.1.1, ruff 0.5.6.
- PostgreSQL 16 on localhost. Database `trustcopilot_test`.
- The release Playwright job lists specs by name. `e2e/release/screen-notifications.spec.ts` is not in that list, so this local run is the UI evidence.

```bash
cd apps/web && npx vitest run lib/delivery-attempts.test.ts
```

Exit status: **0**. Totals: **3 passed**.

```bash
cd apps/web && npx playwright test e2e/release/screen-notifications.spec.ts --retries=0 --reporter=list
```

Exit status: **0**. Totals: **12 passed**, 0 failed, 0 skipped.

Axe JSON under this directory, each with `violationCount` 0:

| File | Width | violationCount |
|---|---|---|
| `axe-notifications-360.json` | 360 | 0 |
| `axe-notifications-768.json` | 768 | 0 |
| `axe-notifications-1440.json` | 1440 | 0 |

Screenshots: `screenshots/notifications-360.png`, `screenshots/notifications-768.png`, `screenshots/notifications-1440.png`.

```bash
cd apps/api && TC_REQUIRE_DB=1 python -m pytest tests/release/test_domain_notifications.py -q --tb=line -p no:warnings
```

Exit status: **0**. Totals: **53 passed**, 0 failed, 0 skipped. The new case is `test_delivery_attempts_payload_matches_the_web_reader`. It reads a PostgreSQL delivery-attempts payload that includes `dead-lettered` and `deduped` (`error_code` `claimed`) and checks `acceptDeliveryAttemptsContract` accepts it. That import is absent on master, so the test fails there.

The full API suite total is the `build` job on this pull request's head, not a local rerun. The only allowed skip remains `tests/test_trust_scoring_blind.py:33`.

Tested commit: filled in after this section is committed. The code under test is that commit; a later edit of this paragraph does not change the product code.
