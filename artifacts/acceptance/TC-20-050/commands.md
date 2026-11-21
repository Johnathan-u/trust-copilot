# Commands

Working directory `apps/api` unless noted. Interpreter `/tmp/tc-venv/bin/python`.

Red, on master `ad5135af1b7bd4fac19a364724130dc3ca0609f6`, database `trustcopilot_red_test`:

```text
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_red_test python -m pytest tests/release/test_crm_salesforce_data.py -q --tb=line
```

Exit 2. 1 collection error.

Green, on `f6a3d1c891b515ac7c90c96b44a0acb736400de8`, database `trustcopilot_test`:

```text
TC_REQUIRE_DB=1 python -m pytest tests/release/test_crm_salesforce_data.py -q --tb=line
```

Exit 0. 10 passed.

Web unit tests, working directory `apps/web`, Node v24.11.1:

```text
npx vitest run tests/unit/jobs-page.test.ts tests/unit/job-history-consumer.test.ts
```

Exit 0. 54 passed.

Migration evidence used `alembic downgrade tc04007b_rate_buckets` and `alembic upgrade head` against `trustcopilot_test`. See `migration.txt`.
