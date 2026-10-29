# TC-02-BUG-018c evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test` (`trustcopilot_test` for the branch, `trustcopilot_master_test` for master). No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6.

Base is `origin/master` `6a26d60e44433720cf329cba08a8f096cb22e682`. The re-run logs below (`review-fix-tests.txt`, `alembic-heads.txt`, `offline-sql-*.txt`, `regression-master.txt`) were produced on the code tree of the commit that renames the revision to `bug018c_one_open_gap` (parent `tc21005_mapping_version`). That commit's SHA is the head named under Testing (author) in the PR. `logs/full-suite-branch.txt` and `logs/full-suite-master.txt` are the earlier full-suite run on `b7da8b3`, before this rename.

| File | What it shows |
|---|---|
| `logs/alembic-heads.txt` | `bug018c_one_open_gap (head)`. |
| `logs/offline-sql-upgrade.txt` | `alembic upgrade tc21005_mapping_version:bug018c_one_open_gap --sql`. Creates the partial unique index. Does not alter `alembic_version`. Does not connect. |
| `logs/offline-sql-downgrade.txt` | Drops only the index. |
| `logs/review-fix-tests.txt` | Index file, safe-collection guard, and notification delivery on this code tree: 65 passed (14 of them are the index file). |
| `logs/regression-master.txt` | The index file copied onto master `6a26d60`: 10 failed, 4 passed. |
| `logs/full-suite-branch.txt` | Full `apps/api` suite on `b7da8b3`, before the revision rename. |
| `logs/full-suite-master.txt` | Full `apps/api` suite on master at that same time, with the old test file copied in. |
| `logs/suite-compare.txt` | Junit comparison for that `b7da8b3` full-suite pair. |
| `logs/ruff-check.txt` | `ruff check` on the first commit's Python files. |
| `logs/ruff-format.txt` | `ruff format --check` on those files. |
| `logs/pre-commit.txt` | `pre-commit run --files` on the first commit's files. |

**Index.** `uq_evidence_gaps_one_open_per_question` on `(workspace_id, questionnaire_id, question_id)` where `status = 'open' AND question_id IS NOT NULL AND gap_type <> 'control_check'`.

**Revision id.** `bug018c_one_open_gap` is 20 characters, so it fits `alembic_version.version_num` (`varchar(32)`). Upgrade does not widen that column. Downgrade drops only the index. The TC-19-008 fresh-database test again expects width 32.

**TC-21-006 scan rows.** `_persist_control_checks` inserts open `control_check` rows and does not set `question_id` or `questionnaire_id`. Several can be open at once, one per control. Those rows are outside the index and outside the pre-scan. The migration does not dedupe them.

**Pre-scan.** Questions that already have more than one open row inside the predicate fail the upgrade with counts and example ids. No row is deleted or closed. `DEDUPE_SQL` keeps the newest open row and sets the older ones to `resolved` with `close_reason` left unchanged.

**Index file.** 14 tests. All 14 passed on this code tree. 10 failed on master `6a26d60`.
