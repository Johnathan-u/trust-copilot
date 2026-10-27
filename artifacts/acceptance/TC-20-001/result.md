# TC-20-001 acceptance evidence

Recorded against implementation commit `4d1c1193b0a95abcfa466735475fae94cf300b11` on branch `tc/int/TC-20-001`. This file is the acceptance record for that commit. No database migration, so upgrade and rollback checks are not applicable.

Credentials are redacted. The release tests use hand-built fixtures and do not call a provider or open a socket for collection.

## Environment

| Item | Value |
| --- | --- |
| OS | Linux 6.12.94+ x86_64 (glibc 2.39) |
| Python | 3.12.3 |
| pytest | 9.1.1 |
| Interpreter | `/tmp/tc-venv/bin/python` (`python` is not on PATH) |
| Postgres | 16.15 on 127.0.0.1:5432, database `trustcopilot_test` |
| Database credentials | redacted |
| `TRUST_COPILOT_TESTING` | `1` |
| Provider network | none |
| OpenAI key | unset |

## Release test (required)

Working directory: `apps/api`.

```bash
python -m pytest tests/release/test_connector_adapter.py -q
```

Invoked as:

```bash
TRUST_COPILOT_TESTING=1 /tmp/tc-venv/bin/python -m pytest tests/release/test_connector_adapter.py -q
```

| Result | Value |
| --- | --- |
| Exit status | 0 |
| Passed | 15 |
| Failed | 0 |
| Skipped | 0 |
| Duration | 0.42s |

Cases covered: success (including store-once idempotency), missing permission, unknown, failure, and rejection of `check_required`, demo, and seeded values. Generic HRIS stays `unsupported`.

## Existing API suite

Unfiltered collection stops on two modules that issue live HTTP at import time (`tests/test_alerts_api.py`, `tests/test_coverage_api.py`) against `localhost:8000`, which is not running. Those modules are manual scripts, not pytest cases. Their contents are not copied here.

```bash
TRUST_COPILOT_TESTING=1 /tmp/tc-venv/bin/python -m pytest -q
```

| Result | Value |
| --- | --- |
| Exit status | 2 |
| Collected | interrupted |
| Errors | 2 (collection) |
| Skipped | 1 |
| Duration | 2.57s |

The remainder of the suite, excluding those two import-time scripts:

```bash
TRUST_COPILOT_TESTING=1 /tmp/tc-venv/bin/python -m pytest -q --tb=line --ignore=tests/test_alerts_api.py --ignore=tests/test_coverage_api.py
```

| Result | Value |
| --- | --- |
| Exit status | 1 |
| Passed | 1296 |
| Failed | 5 |
| Skipped | 3 |
| Warnings | 2624 |
| Duration | 56.06s |

### Failures, and why they are outside this ticket

1. `tests/test_answer_pipeline.py::test_partial_completion_progress` — `OPENAI_API_KEY` is unset. The service raises before generation. This environment has no provider key.
2. `tests/test_p1_multi_tenant_hardening.py::TestAPIQuotaEnforcement::test_generate_answers_blocked_at_quota` — `POST /api/exports/generate/1` returns 503 `OpenAI API key is not configured` before the quota check can return 429. Same missing key.
3. `tests/test_compliance_gaps_unit.py::TestScanAndNotifyCooldown::test_first_call_notifies` — `scan_and_notify_gaps` treats a missing cooldown entry as time `0` and compares it with `time.monotonic()`. Host uptime at the run was 1364 seconds, under the 3600-second cooldown, so the first call returns `reason=cooldown`. `compliance_gaps.py` is unchanged on this branch.
4. `tests/test_notification_fire_points.py::TestGapScanFirePoint::test_gap_scan_notifies_when_gaps_exist` — same cooldown comparison. Gaps exist and `notified` stays false.
5. `tests/test_connector_wizard.py::TestConnectorWizardAPI::test_start_setup` — response `400` with detail `Connector 'azure' is already enabled`. `tests/test_connector_health.py` commits `azure` enabled on workspace 1, and the test database is shared across the process. With that row set back to `enabled=false`, the same test returns 200 `setup_pending` (1 passed). The already-enabled branch is the pre-existing wizard rule. This ticket did not change it.

Connector files exercised with the release tests (AWS, GitHub, Google, cloud, CRM, wizard, health, registry, credentials, ingestion) passed inside the 1296. The CRM suite expects `synced == 0` and no new deals.
