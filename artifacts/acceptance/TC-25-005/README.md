# TC-25-005 acceptance evidence

No credentials, connection strings, or case-study text are recorded here.

| Field | Value |
|---|---|
| Command | `python3 -m pytest tests/release/test_domain_case_studies.py -q` |
| Working directory | `apps/api` |
| Tested SHA | `d939b7e3231e535812f70cd02457838a9849e0c1` |
| Branch | `tc/ca/TC-25-005` |
| Master merged | `1a0e6145cb579954c6d8733199063764ed1c054e` |
| Exit status | 0 |
| Passed | 17 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Warnings | 120 (existing SQLAlchemy `datetime.utcnow` deprecation; not a skip) |
| Duration | 12.94s |
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

The release command was run on a clean tree at the tested SHA, after master `1a0e614` was merged. This evidence directory was committed after that run and does not change the code under test. Required skips: none.

`alembic heads` printed one head: `tc25005_case_study_consent (head)`. History from `075` is `075` → `tc21001_framework_catalog_rights` → `tc11001_model_outcome_codes` → `tc25005_case_study_consent`.

`test_migration_downgrade_round_trip_is_lossless` passed. Upgrade, consent and review writes, downgrade to `tc11001_model_outcome_codes`, and upgrade again deleted no case study row. Archived consent, permission, and review rows matched the live rows after the return upgrade, and the archive tables were then dropped. A row still in the exact post-upgrade state had its snapshot restored on downgrade. A row whose status had moved to `in_review` was not overwritten with that snapshot. A published customer claim with no consent did not come back as a claim. A consented study unpublished on the parent revision, and a consented study whose quote was edited there, both came back as drafts at revision+1 with `publication_authorized` false, so the old consent no longer covered them.

Also run, not part of the ticket command: `python3 -m pytest tests/test_case_studies.py -q` — 13 passed, 0 failed, 0 skipped, 16 warnings, 3.27s, exit 0.

The case-studies page was not opened in a browser. Agreement of the UI consumer is the Node execution inside the release test.
