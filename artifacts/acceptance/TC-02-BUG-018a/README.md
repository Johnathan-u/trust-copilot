# TC-02-BUG-018a evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test` (`trustcopilot_test` for the branch, `trustcopilot_master_test` for master). No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6.

The suites below ran on merge commit `c51c93243d6a5905f5d122608dde9eb2f9cfa8ff` (this evidence directory was added after that). Base is `origin/master` `cfeda5f02136ff4625923e2f551dadb832f286fc`. Alembic head at the last re-parent: `bug018a_gap_closed_at_reason`, parent `tc21003_evidence_link_uniq` (re-parented from `bug019_article_slug_ws` to `tc21002a_canonical_uniq`, then to `tc21003_evidence_link_uniq`). Tests accept this revision or any descendant as head.

| File | What it shows |
|---|---|
| `logs/round-trip.txt` | Schema upgrade/downgrade/upgrade, then the data round trip: an old note is unchanged, a column-only row gets the note on downgrade, and the next upgrade restores `close_reason` and `closed_at`. |
| `logs/offline-sql-upgrade.txt` | `alembic upgrade tc21003_evidence_link_uniq:bug018a_gap_closed_at_reason --sql`. Adds the columns and the backfill `UPDATE`. Does not connect. |
| `logs/offline-sql-downgrade.txt` | `alembic downgrade bug018a_gap_closed_at_reason:tc21003_evidence_link_uniq --sql`. Appends a missing closure note, then drops both columns. |
| `logs/offline-sql-upgrade-stderr.txt` | Alembic's offline-mode log lines for the upgrade SQL. |
| `logs/offline-sql-downgrade-stderr.txt` | Same for the downgrade SQL. |
| `logs/alembic-heads.txt` | `bug018a_gap_closed_at_reason (head)`. |
| `logs/gap-tests-branch.txt` | Closure, regeneration, totals, and the safe-collection guard on the branch: 62 passed. |
| `logs/regression-master.txt` | The 12 new tests copied onto master `cfeda5f` (no `closed_at` column, no migration file): 12 failed, 0 passed. |
| `logs/full-suite-branch.txt` | Full `apps/api` suite on the branch. |
| `logs/full-suite-master.txt` | Full `apps/api` suite on master `cfeda5f`. |
| `logs/suite-compare.txt` | The two junit results compared by test id. |
| `logs/billing-migration-alone.txt` | The billing migration test re-run by itself. |
| `logs/ruff-check.txt` | `ruff check .` in `apps/api`. |
| `logs/ruff-format.txt` | `ruff format --check` on the changed Python files. |
| `logs/pre-commit.txt` | `pre-commit run --files` on the changed files. |

**New tests, all 12, fail on master.** `logs/regression-master.txt`. Closing still appends the note (`test_closing_preserves_reason_text_including_an_embedded_note`). The model has no `closed_at` / `close_reason` (`AttributeError`, and `TypeError` on the constructor). The migration file is absent, so the backfill, round trip, offline SQL, and note-pattern tests fail on `assert path.is_file()`.

**Gap tests on the branch.** 63 passed: 13 closure-column tests (including the lossless downgrade round trip), 16 regeneration tests, 5 totals tests, 29 safe-collection tests. Totals assertions are unchanged; that file no longer calls `setval`.

**Downgrade.** Rows that already end with the historical note keep that `reason` byte for byte. Rows closed only in the columns get `[resolved on regeneration: <code> at <UTC seconds>Z]` appended before the columns are dropped. Upgrade does not write `reason`. The head check accepts `bug018a_gap_closed_at_reason` or any descendant; it does not require that revision to be the only head.

**Full suite, compared by test id** (`logs/suite-compare.txt`).

| | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| Branch `c51c932` | 3029 | 3015 | 3 | 11 |
| Master `cfeda5f` | 3017 | 3003 | 3 | 11 |

The only ids present on the branch and not on master are the 12 new tests, all passed. No shared test changed outcome. The same three failed on both:

- `test_domain_case_studies.py::test_ac3_schema_consumer_and_persisted_outcome_agree_across_retry` — `typescript` is not installed under `apps/web`.
- `test_domain_controls.py::test_routes_agree_on_canonical_contract_and_retry` — node is `v22.23.4`, which that test rejects.
- `test_billing_provider.py::test_migration_fresh_install_upgrade_and_downgrade` — both suites ran at once and both used the side database `trustcopilot_tc24001_migration_test`. Alone, that test passed (`logs/billing-migration-alone.txt`).
