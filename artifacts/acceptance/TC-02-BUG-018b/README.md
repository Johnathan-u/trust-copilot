# TC-02-BUG-018b evidence

Synthetic rows only, on disposable side PostgreSQL databases whose names end in `_test` (`trustcopilot_test` for the branch, `trustcopilot_master_test` for the master suite, `trustcopilot_regression_test` for the copied tests). No model calls and no network calls from the tests. Local Postgres 16 with pgvector. Ruff 0.5.6. The full suites ran one after the other.

Base is `origin/master` `6a26d60e44433720cf329cba08a8f096cb22e682`. Alembic head on this branch: `bug018b_gap_status_checks`, parent `tc21005_mapping_version`. The heads test accepts this revision or any descendant.

| File | What it shows |
|---|---|
| `logs/round-trip.txt` | Downgrade drops both checks and leaves the synthetic row unchanged. Upgrade adds the checks back, validated, and the row is unchanged. |
| `logs/offline-sql-upgrade.txt` | `alembic upgrade tc21005_mapping_version:bug018b_gap_status_checks --sql`. `NOT VALID`, then `VALIDATE CONSTRAINT`, for each check. No `evidence_gaps` data writes. Does not connect. |
| `logs/offline-sql-downgrade.txt` | `alembic downgrade bug018b_gap_status_checks:tc21005_mapping_version --sql`. Drops the two constraints only. |
| `logs/offline-sql-upgrade-stderr.txt` | Alembic's offline-mode log lines for the upgrade SQL. |
| `logs/offline-sql-downgrade-stderr.txt` | Same for the downgrade SQL. |
| `logs/alembic-heads.txt` | `bug018b_gap_status_checks (head)`. |
| `logs/gap-tests-branch.txt` | New checks, closure columns, regeneration, totals, and the safe-collection guard: 72 passed. |
| `logs/regression-master.txt` | The 9 new tests copied onto master `6a26d60`: 7 failed, 2 passed. |
| `logs/full-suite-branch.txt` | Full `apps/api` suite on the branch. |
| `logs/full-suite-master.txt` | Full `apps/api` suite on master `6a26d60`. |
| `logs/suite-compare.txt` | The two junit results compared by test id. |
| `logs/ruff-check.txt` | `ruff check` on `apps/api`. |
| `logs/ruff-format.txt` | `ruff format --check` on the changed Python files. |
| `logs/pre-commit.txt` | `pre-commit run --files` on the changed files. |

**New tests.** Seven fail on master. `test_unknown_status_is_rejected` and `test_unknown_close_reason_is_rejected` insert values master stores, because the columns have no check. The pre-scan, round trip, offline SQL, model-match and heads tests fail because `bug018b_gap_status_checks.py` is not on master (`assert path.is_file()`), and the model-match test also cannot import the new check names.

**Two new tests pass on master.** `test_values_the_app_writes_are_accepted` and `test_non_resolved_row_may_keep_close_reason`. Those pairs already fit the unconstrained `varchar` columns. The second one is the reason the presence check was not added: a non-resolved row may still hold a closure code.

**Gap tests on the branch.** 72 passed: 9 check tests, 13 closure-column tests, 16 regeneration tests, 5 totals tests, 29 safe-collection tests.

**Full suite, compared by test id** (`logs/suite-compare.txt`). Suites ran one after the other.

| | Passed | Failed | Skipped |
|---|---|---|---|
| Branch | 3142 | 2 | 11 |
| Master `6a26d60` | 3133 | 2 | 11 |

The only ids present on the branch and not on master are the 9 new tests, all passed. No shared test changed outcome. The same two failed on both, for this machine's toolchain (Node is v22.23.4, and `apps/web` has no installed TypeScript):

- `test_domain_case_studies.py::test_ac3_schema_consumer_and_persisted_outcome_agree_across_retry`
- `test_domain_controls.py::test_routes_agree_on_canonical_contract_and_retry`

Web-quality tests skipped on both because Node 24 is required. `TC_REQUIRE_WEB_TOOLCHAIN` was left unset so collection could finish.
