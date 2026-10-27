# TC-25-005 acceptance evidence

No credentials, connection strings, or case-study text are recorded here.

| Field | Value |
|---|---|
| Command | `python3 -m pytest tests/release/test_domain_case_studies.py -q` |
| Working directory | `apps/api` |
| Tested SHA | `bd3a0da046ffb3426803c836ce68a511711274f0` |
| Branch | `tc/ca/TC-25-005` |
| Base | `master` `3fc621fd56ef33bc4321f387fdaba66342792498` |
| Exit status | 0 |
| Passed | 12 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 92 (existing SQLAlchemy `datetime.utcnow` deprecation; not a skip) |
| Duration | 9.55s |
| Python | 3.12.3 |
| Node | v22.23.4 locally. The runner type-erases `apps/web/lib/caseStudyConsumer.ts` with the web app's TypeScript, then executes it with `node`, so CI's Node 20 does not need `--experimental-strip-types`. |
| PostgreSQL | 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) |
| Alembic revision after the run | `tc25005_case_study_consent` (`down_revision` `075`) |
| SQLAlchemy | 2.0.55 (pin `>=2.0,<2.1`) |
| Ruff | 0.5.6: `ruff format --check .` (563 files already formatted) and `ruff check .` (all checks passed), from `apps/api` |
| Database | local `trustcopilot_test` (password not recorded) |
| OS | Linux 6.12.94+ x86_64 |

Log: `pytest.out.txt`.

The release command was run on a clean tree at the tested SHA, after master `3fc621f` was merged. This evidence directory was committed after that run and does not change the code under test. Required skips: none.

`test_migration_downgrade_round_trip_is_lossless` passed. Upgrade, consent and review writes, downgrade to `075`, and upgrade again deleted no case study row. Archived consent, permission, and review rows matched the live rows after the return upgrade. A row still in the exact post-upgrade state had its snapshot restored on downgrade. A row whose status had moved to `in_review` was not overwritten with that snapshot. A published customer claim with no consent did not come back as a claim.

Also run, not part of the ticket command: `python3 -m pytest tests/test_case_studies.py -q` — 13 passed, 0 failed, 0 skipped, 16 warnings, 3.13s, exit 0.

The case-studies page was not opened in a browser. Agreement of the UI consumer is the Node execution inside the release test.
