# TC-25-005 acceptance evidence

No credentials, connection strings, or case-study text are recorded here.

| Field | Value |
|---|---|
| Command | `python -m pytest tests/release/test_domain_case_studies.py -q` |
| Working directory | `apps/api` |
| Tested SHA | `ee6864034d2d870b4ede638f637ff3c13ee9926e` |
| Branch | `tc/ca/TC-25-005` |
| Base | `master` `f72def39245abf5cb46c7b3693f687114fa4b1b5` |
| Exit status | 0 |
| Passed | 11 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 82 (existing SQLAlchemy `datetime.utcnow` deprecation; not a skip) |
| Duration | 6.82s |
| Python | 3.12.3 |
| Node | v22.23.4 (used to run `apps/web/lib/caseStudyConsumer.ts`) |
| PostgreSQL | 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) |
| Alembic revision after the run | `076` |
| Database | local `trustcopilot_test` (password not recorded) |
| OS | Linux 6.12.94+ x86_64 |

Log: `pytest.out.txt`.

The release command was run on a clean tree at the tested SHA. This evidence directory was committed after that run and does not change the code under test. Required skips: none.

Also run, not part of the ticket command: `python -m pytest tests/test_case_studies.py -q` — 13 passed, 0 failed, 0 skipped.

The case-studies page was not opened in a browser. Agreement of the UI consumer is the Node execution inside the release test.
