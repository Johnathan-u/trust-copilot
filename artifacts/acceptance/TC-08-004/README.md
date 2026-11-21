# TC-08-004 retrieval eligibility

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-08-004.md`. This folder does not edit the tracker.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_retrieval_isolation.py -q
```

`TC_TEST_DATABASE_URL` pointed at local database `trustcopilot_test` on `127.0.0.1:5432`, user `postgres`. The password is the local development default and is not copied here.

## Failing before

Product code was master `b0b8a01fd2a11914a884630d90ae68fd00291841`. The test file in this change was already present. Log: `failing-before.txt`.

8 failed, 2 passed, exit 1, no skip. The same question did not cross workspaces, and a retrieval-cache read missed after a corpus bump. The answer cache still hit after that bump. Keyword and semantic search still returned a chunk whose document was not indexed. A replaced storage key stayed in the retrieval cache. Soft delete did not tombstone the chunk. Search did not take a permission policy, and the answer cache key did not take a prompt version or a model id.

## Passing after

Same command on product code `445972c4d40e1b7fc2d88e35b7809f47823f7861`. Log: `passing-after.txt`.

10 passed, exit 0, no skip. Citations and both caches stay inside one workspace. After a corpus bump both caches miss, and the other workspace still hits until its own bump. Keyword search, pgvector search, and the semantic fallback drop soft-deleted, not-indexed, and superseded chunks. A reviewer grant that names one document does not return the other document in that workspace. A custom role with every existing flag false gets no chunks. A different model id or prompt version misses. Soft delete tombstones the chunk, bumps the corpus version, and restore clears the tombstone.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document.
