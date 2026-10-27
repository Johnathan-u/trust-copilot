# TC-25-005 acceptance evidence

No credentials, connection strings, or case-study text are recorded here.

| Field | Value |
|---|---|
| Command | `python3 -m pytest tests/release/test_domain_case_studies.py -q` |
| Working directory | `apps/api` |
| Tested SHA | `0d328c6a262b40bbfc5d2aee4d6a35ae4ecf0f0d` |
| Branch | `tc/ca/TC-25-005` |
| Master merged | `1a0e6145cb579954c6d8733199063764ed1c054e` |
| Exit status | 0 |
| Passed | 19 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 138 (existing SQLAlchemy `datetime.utcnow` deprecation; not a skip) |
| Duration | 16.57s |
| Python | 3.12.3 |
| Node | v22.23.4 locally. The runner type-erases `apps/web/lib/caseStudyConsumer.ts` with the web app's TypeScript, then executes it with `node`, so CI's Node 20 does not need `--experimental-strip-types`. |
| PostgreSQL | 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) |
| Alembic heads | `tc25005_case_study_consent (head)` |
| Alembic parent | `tc11001_model_outcome_codes` |
| SQLAlchemy | 2.0.55 (pin `>=2.0,<2.1`) |
| Ruff | 0.5.6: `ruff format --check .` (583 files already formatted) and `ruff check .` (all checks passed), from `apps/api` |
| Vitest | `npm run test:unit` in `apps/web`: 1 file, 6 passed, exit 0 |
| Database | local `trustcopilot_test` (password not recorded) |
| OS | Linux 6.12.94+ x86_64 |

Log: `pytest.out.txt`.

The release command was run on the tree committed as the tested SHA, after master `1a0e614` was merged. PR #30 (`tc25011_demo_proof_summaries`) was still open and not on master, so this revision stays parented on `tc11001_model_outcome_codes`. This evidence directory was committed after that run and does not change the code under test. Required skips: none.

`alembic heads` printed one head: `tc25005_case_study_consent (head)`.

`test_migration_downgrade_round_trip_is_lossless` passed, including parent-revision edits to quote, industry, and quote attribution. Each came back as a draft at revision+1 with review cleared. `test_exact_snapshot_survives_two_round_trips` passed: downgrade, upgrade, downgrade, and upgrade again left the exact post-upgrade row at revision 1, and each downgrade restored the pre-consent published snapshot.

Also run, not part of the ticket command: `python3 -m pytest tests/test_case_studies.py -q` — 13 passed, 0 failed, 0 skipped, 16 warnings, 3.20s, exit 0.

The case-studies page was not opened in a browser. Agreement of the UI consumer is the Node execution inside the release test.
