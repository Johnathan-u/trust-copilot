# TC-08-002 evidence format errors

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-08-002.md`. The runbook is `docs/ops/evidence-format-errors.md`. This folder does not edit the tracker and does not record CI run ids.

The earlier `pytest.txt` and `ci-runs.md` are the PARTIAL verification logs. They are unchanged.

## Command

From `apps/api`:

```sh
python -m pytest tests/release/test_evidence_format_errors.py -q
```

The tests build synthetic files in the process. They do not read a customer document. With `TC_REQUIRE_DB=1` a missing database fails the run instead of skipping. This run used that setting. Nothing was skipped.

## Failing before

Product code was master `34041ee0eefebface47424eb1d61e3a5b323c2f8`. The new test ran against that code. Log: `failing-before.txt`.

Exit 1. 17 failed, 6 passed, 0 skipped. A corrupt `.xlsx` and an empty file stored `Parse returned no content; document not indexed`. A `.doc` with python-docx installed was `internal_error`. A `.xls` was swallowed. The three PDF cases, a readable text file, and a refused `.csv` upload passed.

## Passing after

Same command on product code `8624eca676041359e7cff947974a12cbcfc16cf6`. Log: `passing-after.txt`.

23 passed, 0 failed, 0 skipped, exit 0. Pytest also printed 28 warnings from `datetime.utcnow` in existing models. A corrupt workbook, a legacy `.doc` and `.xls`, an unreadable `.docx`, and an empty non-PDF file each store the fixed reason and next action. Status is `failed`. No chunks are written. The marker and the path are absent. Workspace 2 receives 403. A readable `.xlsx`, `.docx`, and `.txt` still parse.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, openpyxl 3.1.5, python-docx 1.2.0, pypdf 6.21.3, PostgreSQL 16.15, pgvector 0.6.0. Fixtures are synthetic. No customer document. No new migration.
