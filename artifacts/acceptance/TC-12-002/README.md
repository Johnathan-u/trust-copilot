# TC-12-002 answer revision

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-12-002.md`. The operator note is `docs/ops/answer-edits.md`. This folder does not edit the tracker. It does not record a CI run id.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_answer_revisions.py -q
```

`TC_TEST_DATABASE_URL` was unset. The suite used local database `trustcopilot_test` on `127.0.0.1:5432`, user `postgres`. The password is the local development default and is not copied here.

From `apps/web`:

```sh
npx vitest run tests/unit/answer-save.test.ts
```

## Failing before

Product code was master `ba789896951bc60e8f67842c87f67a0b50fbe988`. The test file in this change was already present. The answer routes were the master versions. Log: `failing-before.txt`.

2 failed, exit 1, no skip. Both saves returned 200. The second save replaced the stored text. A save that omitted `updated_at` also returned 200 and replaced the text.

## Passing after

Same command on product code `f503e194f226c696c6f55be71aa28f4d5f80874b`. Log: `passing-after.txt`.

2 passed, exit 0, no skip. The stale client receives 409 and the stored text stays the winner's. A later questionnaire read returns that text. A save with no `updated_at` is 409 and the row stays.

The web unit file is 4 passed (the loaded revision, plus HTTP 403, 409, and 500). Each failure keeps the typed text and `Not saved yet`.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Node 24.22.3, vitest 5.0.5. Fixtures are synthetic. No customer document. No migration.
