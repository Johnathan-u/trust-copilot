# TC-19-008 acceptance evidence

Real Slack, Gmail, and SMTP qualification is **BLOCKED**. No mailbox, Slack workspace, token, or outbound notification call was used. Email uses the console provider. Slack uses the labelled development stub.

## Environment

- Python 3.12.3 locally (`/tmp/tc-venv/bin/python`). GitHub CI uses Python 3.11.
- pytest 9.1.1, ruff 0.5.6, SQLAlchemy 2.0.55, psycopg2 2.9.13
- Local PostgreSQL 16 with the `vector` extension, database `trustcopilot_test`
- Master pins `sqlalchemy>=2.0,<2.1`. psycopg v3 was not added.
- `alembic heads`: `077 (head)`. Parent revision is `075`.

## Release tests

Command, from `apps/api`:

```bash
TC_REQUIRE_DB=1 SESSION_SECRET=test-secret /tmp/tc-venv/bin/python -m pytest tests/release/test_notification_delivery.py -q --tb=line -p no:warnings
```

Exit status: **0**

Totals: **10 passed**, 0 failed, 0 skipped.

That file includes a fresh-database upgrade to `077`, downgrade to `075`, and upgrade again. The side database is created with the same role as `TC_TEST_DATABASE_URL` or `DATABASE_URL`.

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

Output: `077 (head)`.

```bash
cd apps/api && TC_REQUIRE_DB=1 SESSION_SECRET=test-secret /tmp/tc-venv/bin/python -m pytest -rs -q --tb=line -p no:warnings
```

Exit status: **0**

Totals: **1338 passed**, 3 skipped, 0 failed.

Skips: blind pack not found, no reviewed workspace controls, no questionnaires.

```bash
cd apps/web && npm run build
```

Exit status: **0**. Next.js compiled and generated 34 pages. The notifications page is in that build.

## Browser

Signed in as `demo@trust.local` on `http://127.0.0.1:3000/dashboard/notifications`. Email and Slack started checked. In-app started unchecked, stayed checked after a reload when enabled, and stayed unchecked after it was turned off again. The activity log showed a dev-stub send as not delivered to the provider.

## Not in this run

`tests/test_alerts_api.py` and `tests/test_coverage_api.py` are not in the test tree on this branch (they were moved out of `tests/` on master). They were not run.
