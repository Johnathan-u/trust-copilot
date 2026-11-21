# TC-08-006 archive revalidation

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-08-006.md`. This folder does not edit the tracker.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_archive_revalidation.py -q
```

`TC_TEST_DATABASE_URL` was unset. The suite used local database `trustcopilot_test` on `127.0.0.1:5432`, user `postgres`. The password is the local development default and is not copied here.

## Failing before

Product code was master `ad5135af1b7bd4fac19a364724130dc3ca0609f6`. The test file in this change was already present. Log: `failing-before.txt`.

8 failed, 2 passed, exit 1, no skip. Archive still bumped the corpus version and hid the chunk, and an eligible chunk could still be accepted as evidence. Approving an answer did not record the supporting document. The approved row stayed plain approved after archive, after restore, and after a storage-key replacement. Export enqueue returned a job instead of 409. The export worker tried to read the questionnaire object. Accepting a chunk from a soft-deleted, not-indexed, or replaced document succeeded.

## Passing after

Same command on this change. Log: `passing-after.txt`.

10 passed, exit 0, no skip. Approval records the supporting document id on the citation. Archive keeps the approved text and status and sets `support_stale`. Restore does not clear it. Export is 409 and lists the included answer id, and an insufficient-evidence row is not listed. A new revision approved against an active document exports. A replaced storage key is stale and blocks export. The worker raises `export_support_stale` before it reads the file. Accept-suggested returns 409 for a soft-deleted, not-indexed, or replaced chunk and still accepts an eligible chunk.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document.

From `apps/web`, `npx vitest run tests/unit/ai-review-copy.test.ts tests/unit/review-approved-draft.test.ts tests/unit/answer-save.test.ts` is 21 passed. The review page shows `Stale source` when the questionnaire answer has `support_stale: true`, and does not show it when that field is absent.
