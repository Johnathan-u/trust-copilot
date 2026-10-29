# TC-02-BUG-018c evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test` (`trustcopilot_test` for the branch, `trustcopilot_master_test` for master). No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6.

Base is `origin/master` `6a26d60e44433720cf329cba08a8f096cb22e682`. Alembic parent at this push: `tc21005_mapping_version` (single head on master). PR #76 (`tc21006_gap_evaluation`) and PR #78 (`bug018b_gap_status_checks`) were still open. This revision will be re-parented with a merge commit when those land.

| File | What it shows |
|---|---|
| `logs/alembic-heads.txt` | `bug018c_one_open_gap_per_question (head)`. |
| `logs/offline-sql-upgrade.txt` | `alembic upgrade tc21005_mapping_version:bug018c_one_open_gap_per_question --sql`. Widens `alembic_version.version_num` to `varchar(64)`, then creates the partial unique index. Does not connect. |
| `logs/offline-sql-downgrade.txt` | Drops only the index. |
| `logs/gap-tests-branch.txt` | New index tests, closure, regeneration, totals, and the safe-collection guard: 76 passed. |
| `logs/regression-master.txt` | The new file on master `6a26d60`: 9 failed, 4 passed. |
| `logs/full-suite-branch.txt` | Full `apps/api` suite on the branch, run in parallel with master. |
| `logs/full-suite-master.txt` | Full `apps/api` suite on master, with the new test file copied in. |
| `logs/suite-compare.txt` | The two junit results compared by test id, plus the alone re-runs. |
| `logs/ruff-check.txt` | `ruff check` on the changed Python files. |
| `logs/ruff-format.txt` | `ruff format --check` on those files. |
| `logs/pre-commit.txt` | `pre-commit run --files` on the changed files. |

**Index.** `uq_evidence_gaps_one_open_per_question` on `(workspace_id, questionnaire_id, question_id)` where `status = 'open' AND question_id IS NOT NULL AND gap_type <> 'control_check'`.

**TC-21-006 scan rows.** `_persist_control_checks` inserts open `control_check` rows and does not set `question_id` or `questionnaire_id`. Several can be open at once, one per control. `close_reason = 'evidence_sufficient'` is written only when a scan row is resolved. Those open rows are outside the index and outside the pre-scan. The migration does not dedupe them.

**Pre-scan.** Questions that already have more than one open row inside the predicate fail the upgrade with counts and example ids. No row is deleted or closed. `DEDUPE_SQL` is documented for an operator. It keeps the newest open row and sets the older ones to `resolved` with `close_reason` left unchanged. It does not use `superseded` or `evidence_sufficient`.

**Version column.** The revision id is 33 characters. Upgrade widens `alembic_version.version_num` from `varchar(32)` to `varchar(64)`. Downgrade does not shrink it. The TC-19-008 fresh-database test now expects 64 at head.

**New tests.** 9 of 13 fail on master. The four that pass there do not need the index: open plus resolved, several open control-check rows, teardown of a committed row, and generation still opening one gap.

**Full suite, compared by test id** (`logs/suite-compare.txt`).

| | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| Branch, parallel run | 3159 | 3144 | 4 | 11 |
| Master, parallel run, new tests copied in | 3159 | 3136 | 12 | 11 |

After that run, `test_migration_upgrades_and_downgrades_on_a_fresh_database` was updated to expect width 64 and passed alone. The billing migration test passed alone on both sides. The two environmental failures are the same on both: case-study consumer (no TypeScript under `apps/web`) and canonical-contract node check (v22.23.4, test requires v24).
