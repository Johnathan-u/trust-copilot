# TC-03-004 audited migration snapshot

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-03-004.md`. The runbook is `docs/ops/migration-baseline.md`. This folder does not edit the tracker.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_migration_baseline.py -q
```

The tests create side databases from the suite URL and drop them. The shared suite database is not migrated by this file.

## Failing before

Product code was master `b50d6760579fb8e0f487f6555e602e902d3b7055`. `tests/release/test_migration_baseline.py` was not in the tree. Log: `failing-before.txt`.

Exit 4. No tests ran. Pytest reported `file or directory not found`.

## Passing after

Same command on product code `a0aed61d49ae3484158811a96bfb987c7774a5ab`. Log: `passing-after.txt`.

4 passed, exit 0, no skip. A fresh empty database upgrades to the single runtime head. The synthetic revision-075 snapshot upgrades to that head, keeps audited row counts, foreign keys, storage keys, and answer text, and writes `backfill-report.json`. Downgrade to `075` and a second upgrade to the head keep the same keys and answer text. A database stamped at `075` with no core tables is refused and stays at `075`.

## Backfill report

`backfill-report.json` from `qualify`. `fresh-upgrade.json` from `fresh`. Both have `ok` true and `head_count` 1. The discovered head is `tc20050_crm_pipeline_sync`. The script does not contain that name.

Audited counts before and after: workspaces 2, users 1, workspace_members 1, documents 1, questionnaires 1, questions 1, answers 1. No baseline table lost rows. The only increase is `frameworks`, 0 to 9, and `tc21001_framework_catalog_rights` reports `rows_affected` 9. `question_cell_mapping` reports `rows_affected` 1 on `questions`. Nineteen other revisions contain data statements and report `rows_affected` 0 on this fixture. 21 backfill revisions, 10 rows affected in total.

Foreign keys: 181 at revision `075`, 231 at the head, `foreign_keys_missing` empty.

Sampled storage keys: `synthetic/audited-snapshot/policy.pdf`, `synthetic/audited-snapshot/questionnaire.xlsx`. Sampled answer: `Access reviews run each quarter.` Both pairs match after the upgrade, after downgrade to `075`, and after the second upgrade.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document. No new migration.
