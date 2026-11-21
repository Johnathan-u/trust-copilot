# Audited migration snapshot

Operator notes for upgrading a database that is still at the planning baseline
(TC-03-004). The baseline commit is `c20f949161ac12a619b396d30904448ffd74d532`.
In that tree the only alembic head is revision `075`. This page does not add a
migration. Do not paste `DATABASE_URL`, a password, or a connection string into
a ticket, a log excerpt, or the backfill report.

Take a backup before you upgrade a database you need to keep. See
[Database backup](BACKUP_RESTORE.md). Run the commands below against a copy
until you have read a successful report.

The tool refuses to `stamp` a version. A database whose `alembic_version` says
`075` but is missing the core tables (workspaces, users, documents,
questionnaires, questions, answers, and the file and answer columns) exits 2
and leaves that version row unchanged.

## Discover the head

From `apps/api`:

```sh
alembic heads
alembic current
```

`alembic heads` must print one revision. The upgrade commands below discover
that same revision themselves. They do not name it in the script.

## Rehearse with the synthetic snapshot

`qualify` needs an empty disposable database. It upgrades that database to
`075`, loads `scripts/fixtures/audited_snapshot_075.sql` (synthetic workspace,
user, document, questionnaire, question, and answer), upgrades to the single
head, writes the report, downgrades to `075`, checks the original rows, then
upgrades to the head again.

```sh
cd apps/api
DATABASE_URL="postgresql://..." python scripts/migration_baseline.py qualify \
  --report /tmp/backfill-report.json
```

Exit 0 means the report's `ok` field is true. The rehearsal database ends at
the head.

## Upgrade a database that is already at revision 075

`upgrade` does not insert fixture rows and does not downgrade. The database
must already be at revision `075` and must have the core tables. A database
that is empty, already at head, or stopped on a later revision is refused.

```sh
cd apps/api
DATABASE_URL="postgresql://..." python scripts/migration_baseline.py upgrade \
  --report /tmp/backfill-report.json
```

## Fresh database

An empty database still uses `alembic upgrade head`. The same check is:

```sh
cd apps/api
DATABASE_URL="postgresql://..." python scripts/migration_baseline.py fresh \
  --report /tmp/fresh-upgrade.json
```

`fresh` refuses a database that already has tables or an alembic version.

## Read the backfill report

The report is JSON. It does not contain `DATABASE_URL`.

| Field | Meaning |
|---|---|
| `ok` | Survival checks passed. |
| `head_count` | Must be 1. |
| `head_revision` | The revision `alembic heads` printed. |
| `revision_before` / `revision_after` | `075`, then `head_revision`. |
| `sampled_storage_keys` | `documents.storage_key` and `questionnaires.storage_key` before the upgrade. |
| `sampled_answer_texts` | `answers.text` before the upgrade. The `*_after` fields must match. |
| `survival.row_counts_match` | No baseline table lost rows, and the audited tables (workspaces, users, workspace members, documents, questionnaires, questions, answers) kept the same counts. |
| `survival.row_count_increases` | Tables that gained rows. A catalog backfill can insert into `frameworks`. |
| `survival.row_count_losses` | Must be empty. |
| `survival.foreign_keys_missing` | Foreign keys present at `075` that are absent at the head. Must be empty. |
| `backfills` | Each later revision whose upgrade reaches `INSERT`, `UPDATE`, or `DELETE`. |
| `backfills[].rows_affected` | Inserted, deleted, and updated rows in the tables that revision names. `null` when a changed table has no single-column primary key. |
| `rollback` | Present for `qualify` only. `ok` means the downgrade to `075` kept the sampled keys, answer text, and baseline counts. |
| `reupgrade` | Present for `qualify` only. `ok` means the second upgrade reached the same head and kept the sampled keys and answer text. |

`rows_affected` is 0 when that revision's data statements did not change a row in this database. A column added in the same revision counts as an update when the stored row image changes.

## Rollback

`upgrade` leaves the database at the head. To return that database to the audited baseline:

```sh
cd apps/api
alembic downgrade 075
```

`qualify` already does this once, checks the synthetic file keys and answer text, then runs `alembic upgrade head` again. Use that rehearsal on a copy before you downgrade a database you need to keep.

Do not `alembic stamp` to skip a revision that failed. If `alembic downgrade 075` fails, restore the backup and leave the version row where the failed command stopped.

This change does not add a migration, so there is no new revision to reverse. Existing downgrades are the ones `qualify` runs.
