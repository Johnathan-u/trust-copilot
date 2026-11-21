# TC-20-050 acceptance evidence

Paginated Salesforce pipeline sync, stable deal identity, and the shared `crm_sync` job. This note does not accept the ticket.

## DoD6

N/A. The owner ruling for this work is that Salesforce and HubSpot are built against fixtures and a mock server. There is no Salesforce account, no credential, and no network call to Salesforce. The release test talks only to a server on `127.0.0.1`. Hostnames of Salesforce are refused. HubSpot remains the labeled example until TC-20-053.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. The test file was copied onto master `ad5135af1b7bd4fac19a364724130dc3ca0609f6`. The product change was not on that tree. Database `trustcopilot_red_test` at `127.0.0.1:5432`.

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_red_test python -m pytest tests/release/test_crm_salesforce_data.py -q --tb=line
```

| Command | Exit | Total |
|---|---|---|
| the red command above | 2 | 1 error during collection |

Collection stopped on `ModuleNotFoundError: No module named 'app.models.crm_connection'`. Log: `failing-before.txt`.

## Green command

Same interpreter and the same test, on the product commit. Database `trustcopilot_test` at `127.0.0.1:5432`.

```text
TC_REQUIRE_DB=1 python -m pytest tests/release/test_crm_salesforce_data.py -q --tb=line
```

## SHA

The green test ran on `f6a3d1c891b515ac7c90c96b44a0acb736400de8`. This directory was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), user `postgres`
- Node v24.11.1 for the web unit tests (`jobs-page.test.ts`, `job-history-consumer.test.ts`): 54 passed

## Totals

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 10 passed, 92 warnings, 4.96s |
| `python -m pytest tests/test_crm_connectors.py tests/test_deals.py tests/test_job_progress_counters.py -q --tb=line` together with the release file and two config-contract checks | 0 | 47 passed |

The release file reported no skip. Logs: `passing-after.txt`. Migration upgrade, dedupe, downgrade, and restore: `migration.txt`. Revision `tc20050_crm_pipeline_sync`.

No CI run id is recorded here.
