# TC-25-005 acceptance evidence

No credentials, connection strings, or case-study text are recorded here.

| Field | Value |
|---|---|
| Command | `python3 -m pytest tests/release/test_domain_case_studies.py -q` |
| Working directory | `apps/api` |
| Tested SHA | `7caa4f340bf621d1d1022f07db625d376b196562` |
| Branch | `tc/ca/TC-25-005` |
| Base | `master` `f72def39245abf5cb46c7b3693f687114fa4b1b5` |
| Exit status | 0 |
| Passed | 12 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 92 (existing SQLAlchemy `datetime.utcnow` deprecation; not a skip) |
| Duration | 10.74s |
| Python | 3.12.3 |
| Node | v22.23.4 (used to run `apps/web/lib/caseStudyConsumer.ts`) |
| PostgreSQL | 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) |
| Alembic revision after the run | `tc25005_case_study_consent` |
| Database | local `trustcopilot_test` (password not recorded) |
| OS | Linux 6.12.94+ x86_64 |

Log: `pytest.out.txt`.

The release command was run on a clean tree at the tested SHA. This evidence directory was committed after that run and does not change the code under test. Required skips: none.

`test_migration_downgrade_round_trip_is_lossless` passed. Upgrade, consent and review writes, downgrade to `075`, and upgrade again deleted no case study row. Archived consent, permission, and review rows matched the live rows after the return upgrade. A row still in the exact post-upgrade state had its snapshot restored on downgrade. A row whose status had moved to `in_review` was not overwritten with that snapshot. A published customer claim with no consent did not come back as a claim.

Also run, not part of the ticket command: `python3 -m pytest tests/test_case_studies.py -q` — 13 passed, 0 failed, 0 skipped, 16 warnings, 2.81s, exit 0.

The case-studies page was not opened in a browser. Agreement of the UI consumer is the Node execution inside the release test.
