# TC-07-008 private downloads

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-07-008.md`. The runbook is `docs/ops/private-downloads.md`. This folder does not edit the tracker and does not record CI run ids.

The earlier `pytest.txt`, `pytest-preview.txt`, `pytest-export.txt`, and `ci-runs.md` files are the PARTIAL verification logs. They are unchanged.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_download_safety.py -q
```

The tests use the suite database. They create a synthetic user, document, export, and trust-request attachment, then delete those rows.

## Failing before

Product code was master `c44e53b9386d5564781170b19238f7e37dd288ef`. `tests/release/test_download_safety.py` was not in the tree. Log: `failing-before.txt`.

Exit 4. No tests ran. Pytest reported `file or directory not found`.

## Passing after

Same command on product code `dd40eae4e06db8a2034578606c365d88c0736047`. Log: `passing-after.txt`.

10 passed, 0 failed, 0 skipped, exit 0. Pytest also printed 24 warnings from `datetime.utcnow` in existing models. A current session downloads the document, the hashed export, the legacy export, and the attachment with `nosniff` and without a presigned URL. An expired session and a revoked workspace session are 401 on all four. A cross-workspace id is 404 and the body has no foreign bytes. A stored key with `..`, a leading slash, or a `..` segment is 400 before any storage read. An archived document is not streamed. A public bucket is refused. Production must prove the public-access block. A new bucket is created private. A public bucket is not swallowed at startup.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document. No new migration.
