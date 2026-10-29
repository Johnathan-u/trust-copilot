# TC-02-BUG-018c evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test` (`trustcopilot_test` for the branch, `trustcopilot_master_test` for master). No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6.

Base is `origin/master` `5b97a33d0cd43d07ebba901901d5433d7725eb43`. The re-parent suites were produced on the code tree of commit `0e2c731221e795879274b447be3456cf38982328` (merge of that master; `down_revision` is `bug018b_gap_status_checks`). Writing this sentence moved the head, same as TC-02-BUG-018b. Those suites ran one after another on `trustcopilot_test`: index file 14 passed, safe-collection guard 29 passed, status-check file 10 passed, domain compliance gaps 8 passed, questionnaire-gap integration 6 passed, compliance-gap unit 5 passed, notification delivery 22 passed. `logs/full-suite-branch.txt` and `logs/full-suite-master.txt` are the earlier full-suite run on `b7da8b3`.

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

**Re-parent.** `bug018c_one_open_gap` revises `bug018b_gap_status_checks`. `alembic heads` is that one revision. The scan gap type is `CONTROL_CHECK` on the model; the compliance-gaps route imports it.

**Index file.** 14 tests, 14 passed on `0e2c731`. 10 of those 14 failed on the pre-merge master `6a26d60`.
