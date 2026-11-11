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

`result.json` records head `2f5ffb040161fd7a4d4b5f59b3a7d14f2b976b77`.

| Event | Run | `build` | `web-release-e2e` |
|---|---|---|---|
| push | [42932293744](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932293744) | [130233765516](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932293744/job/130233765516) | [130233765114](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932293744/job/130233765114) |
| pull_request | [42932316388](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932316388) | [130233839626](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932316388/job/130233839626) | [130233840251](https://github.com/Johnathan-u/trust-copilot/actions/runs/42932316388/job/130233840251) |

Both jobs are green on both events. Backend `pytest -rs` (exit 0):

```text
tests/release/test_ci_integration.py ..........
tests/release/test_ci_storage_roundtrip.py .
=========== 6436 passed, 1 skipped, 52 warnings in 847.48s (0:14:07) ===========
```

The pull_request build printed the same two focused lines and
`6436 passed, 1 skipped, 52 warnings in 809.21s (0:13:29)`. The ten dots are
the integration file, including the database negative controls. The storage
round-trip is the single dot. Neither file skipped. The only session skip is
`tests/test_trust_scoring_blind.py:33` (`external_data`).

Environment from those logs: Python 3.11.18, pytest 9.1.1, Playwright 1.64.1,
Chrome for Testing 156.0.8078.4 (playwright chromium v1248),
`pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`,
`motoserver/moto:5.2.5@sha256:59a1965d845249b04def37a0e2565f9cc6c44543cb89b68e90f28f344b3b0d1a`
(moto, Apache-2.0). The moto step printed `buckets ready` after the final probe.

`ui-23.spec.ts: 30 passed, 0 failed, 0 skipped, 0 flaky` and
`playwright exit 0; axe check exit 0` on the push `web-release-e2e` job.

This evidence commit is later than `2f5ffb0`. Its own `build` and
`web-release-e2e` runs are a separate check. They do not replace the tested
head above.

## Rollback

Revert the change. The runner discards the moto container. Nothing is persisted.
