# TC-09-004 workbook preflight

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-09-004.md`. This folder does not edit the tracker.

## Command

From `apps/api`:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_workbook_preflight.py -q
```

`TC_TEST_DATABASE_URL` pointed at local database `trustcopilot_test` on `127.0.0.1:5432`, user `postgres`. The password is the local development default and is not copied here.

## Failing before

Product code was master `75437e34e570a16500cbea5e5c24f9f8578f47f3`. The test file in this change was already present. Log: `failing-before.txt`.

8 failed, 4 passed, exit 1, no skip. A `.xlsm` macro package was refused with the extension allowlist sentence, not the export sentence. A macro `.xlsx`, an encrypted package, and a legacy `.xls` were stored (HTTP 200) with a questionnaire and a parse job. Parse of the macro package did not raise. Parse of the encrypted package and the legacy `.xls` raised `WorkbookUnreadable` with the generic sentence. The worker then continued past the macro parse.

## Passing after

Same command on the product code in this change. Log: `passing-after.txt`.

12 passed, exit 0, no skip. Intake and `create_export_from_questionnaire` raise the same `UnsupportedWorkbookStructure` sentence for macros (`macros`), encryption (`encryption`), and legacy BIFF (`legacy .xls`). Those uploads store no questionnaire, question, job, or object. A supported `.xlsx` is stored, questions are saved, and named ranges, merges, validations, and styles survive export. A corrupt file that is none of those shapes still raises `WorkbookUnreadable`. Another workspace is 403 and stores nothing.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, openpyxl 3.1.5, SQLAlchemy 2.0.55, Alembic 1.20.1, PostgreSQL 16.15, pgvector 0.6.0. The web unit test that the upload notice keeps the sentence used Node 24.22.3. Fixtures are synthetic. No customer workbook.
