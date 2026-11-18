# TC-10-002a acceptance evidence

Follow-up of TC-10-002, from the post-merge review of #211 (comment 6789737115 on merged `4a2403d`). The review accepted the parent and left two documentation corrections.

## What changed

- `docs/release/tickets/TC-10-002.md` no longer says that upgrading again does not put archived rows back. The rollback note names the upgrades that restore archives: `tc17003`, `tc17004`, and `tc19010`, and `tc23001` only in part.
- `artifacts/acceptance/TC-10-002/README.md` and `result.json` label PostgreSQL 16.15 as inferred. The CI logs for that record show the image digest `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. They do not print `SELECT version()`. The version is the one named by the workflow comment on that digest in `.github/workflows/ci.yml`.

No application code, migration, authentication, or authorization path changed. The new release test is the only test change. It does not skip, and it does not touch a database.

## Release test

`apps/api/tests/release/test_tc10002a_rollback_wording.py`

| Test | Checks |
|---|---|
| `test_tc10002a_rollback_doc_names_archive_restores` | The rollback section no longer says an upgrade leaves archived rows unrestored. It names `tc17003`, `tc17004`, and `tc19010` as restores, and says `tc23001` restores archived rows only in part. |
| `test_tc10002a_postgresql_16_15_is_labelled_inferred` | The TC-10-002 README line that states PostgreSQL 16.15 also says that version is inferred from the digest. `result.json` `environment.postgresql` is not the bare value `16.15`, and `postgresql_note` says the CI logs show only the digest. |

Command, from `apps/api`:

```
python -m pytest tests/release/test_tc10002a_rollback_wording.py -q --tb=short -p no:cacheprovider
```

Python 3.12.3, pytest 9.1.1. Base before the wording edit: `d69109e720df3a697ff4af9eb1b222ae1553a628`.

| Artifact | Result |
|---|---|
| `failing-before.txt` | 2 failed, 0 passed. Exit 1. |
| `passing-after.txt` | 2 passed, 0 failed, 0 skipped. Exit 0. |

## CI

`build` and `web-release-e2e` run IDs for the implementation head, on both `push` and `pull_request`, are in `ci-runs.md` once those runs are green. This directory does not accept TC-10-002 or TC-10-002a.
