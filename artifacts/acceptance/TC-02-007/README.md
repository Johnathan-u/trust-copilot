# TC-02-007 evidence

Parent of TC-02-007b (PostgreSQL TCP readiness) and TC-02-007c (session-cookie
deadline). This directory is the parent evidence. The children do not complete
the storage service, the spec gate or the collection-time skip gate.

## What this change proves

* The `build` job starts digest-pinned moto (`motoserver/moto`, Apache-2.0) on
  `127.0.0.1:9000`, waits with a 60-attempt loop plus a mandatory final probe,
  creates `test-raw` and `test-exports`, and exports generated masked credentials.
* `TC_REQUIRE_STORAGE=1` on the backend step fails the session when that service
  is down, and a `storage` test cannot skip.
* `TC_REQUIRE_DB=1` fails an unmarked collection-time skip. The
  `external_data` skip in `tests/test_trust_scoring_blind.py` stays allowed.
* The web-release candidate loop fails when a listed spec file is missing.
  Every candidate, including `e2e/release/ui-23.spec.ts` (30 cases), is passed
  to `--require-spec`.
* `tests/release/test_ci_storage_roundtrip.py` uploads, downloads and deletes
  one synthetic object through `StorageClient`.

In-memory storage fakes used by other tests are unchanged. No product runtime
code is changed. No credential is committed.

## Commands

From `apps/api`, after the disposable Postgres and moto services are up and
`TC_TEST_S3_*` point at moto:

```bash
python -m pytest tests/release/test_ci_integration.py tests/release/test_ci_storage_roundtrip.py -q
pytest -rs
```

`result.json` records the exact-head `build` and `web-release-e2e` runs for
both the `push` and `pull_request` events, the session totals, and the focused
results. Those ids are filled from the GitHub Actions logs of the head under
test. A later evidence-only commit is checked by its own runs; it does not
replace the tested head recorded here.

## Rollback

Revert the change. The runner discards the moto container. Nothing is persisted.
