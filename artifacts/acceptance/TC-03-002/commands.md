# Commands

Working directory notes are on each line. The database URL and password were not printed.

```
cd apps/api && python -m pytest tests/release/test_compose_stack.py -q --tb=line
```

Baseline (compose files at `80607881320e1fa2c6416c55730eb98a56449f26`, test file present): exit 1, 5 failed, 2 passed.

Same command on the branch: exit 0, 7 passed.

```
cd apps/api && ruff check .
cd apps/api && ruff format --check .
```

Both exit 0.

```
python scripts/security/secret_inventory.py tree
```

From the repo root. Exit 0. `{"block": 0, ...}`.

```
cd apps/api && python -m pytest -rs --tb=line
```

Env: `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1`, `TRUST_COPILOT_TESTING=1`, `SESSION_SECRET=test-secret`, Node 24.22.1 on `PATH`. Fresh local database `tc03002_fresh_test` on the pinned pgvector container. Exit 0. 3275 passed, 1 skipped.

```
docker compose -p tc03002 -f docker-compose.yml -f /tmp/tc03002-override.yml up -d postgres
docker compose -p tc03002 -f docker-compose.yml -f /tmp/tc03002-override.yml restart postgres
```

The override only moved the host port to `127.0.0.1:55434` because `tc-ci-pg` already held 5432, and renamed the container. It did not change the security options. A gitignored `.env` copied from `.env.example` satisfied `env_file` and was removed afterwards.
