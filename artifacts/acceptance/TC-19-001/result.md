# TC-19-001 acceptance evidence

Real Slack and Gmail sandbox qualification is **BLOCKED**. The runs below use hand-built HTTP fixtures only. No Slack workspace, Google Cloud OAuth client, Gmail mailbox, live token, or outbound network call was used.

## Environment

- Python 3.12.3
- pytest 9.1.1
- httpx 0.28.1 (`httpx.MockTransport`)
- Local PostgreSQL 16.15 with the `vector` extension, database `trustcopilot_test` (used only by the existing Slack/Gmail tests; credentials not recorded)
- Host Linux. `python` is not on `PATH`. Interpreter: `/tmp/tc-venv/bin/python`
- No `SLACK_*` or `GMAIL_*` credentials in the environment

## Wiring tests

Command, from `apps/api`:

```bash
/tmp/tc-venv/bin/python -m pytest tests/release/test_message_provider_wiring.py -q
```

Exit status: **0**

Totals: **41 passed**, 0 failed, 0 skipped.

## Existing Slack and Gmail tests

Command, from `apps/api`:

```bash
/tmp/tc-venv/bin/python -m pytest tests/test_phase_d_slack.py tests/test_phase_e_slack_ingest.py tests/test_phase_f_gmail.py tests/test_phase_c_notifications.py tests/test_notification_fire_points.py -q
```

Exit status: **0**

Totals: **95 passed**, 0 failed, 0 skipped. Deprecation warnings from `datetime.utcnow` in SQLAlchemy defaults are pre-existing and not from this ticket.

## Not run

`tests/test_alerts_api.py` and `tests/test_coverage_api.py` perform live HTTP calls at import. They were ignored and were not part of either command. A full API suite must pass `--ignore=tests/test_alerts_api.py --ignore=tests/test_coverage_api.py`.

## Commit

SHA is filled in after the implementation commit. See the following line once updated:

`IMPLEMENTATION_SHA=`

## Sandbox

**BLOCKED.** Fixture results do not close provider acceptance.
