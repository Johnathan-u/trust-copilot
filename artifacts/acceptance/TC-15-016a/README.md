# TC-15-016a documents list contract

Local cloud VM, Linux. Python 3.12.3. Interpreter `/tmp/tc-api/bin/python`. SQLAlchemy 2.0.58. The release test uses SQLite and an injected reviewer. It does not qualify PostgreSQL or the real session dependency. No Postgres server was required for this file.

Node v24.22.1 and npm 11.19.1 ran the documents page spec. Playwright 1.64.1, Chromium from Playwright's cache.

This note does not accept TC-15-016 or TC-15-016a.

## Failing before

Working directory `apps/api`. The new test file was in the tree. `GET /api/documents` still returned one JSON array and ignored `page`, `sort`, and `order`. Rows had no `source_eligibility`. `GET /api/documents/{id}/content` was 404.

```sh
/tmp/tc-api/bin/python -m pytest tests/release/test_tc_15_016a_documents_list.py -q --tb=line
```

Exit status 1. 4 failed, 7 warnings, 0.70s. Log: [failing-before.txt](failing-before.txt).

## Passing after

Same command, after the list envelope, the row fields, the content route, and the page change.

Exit status 0. 4 passed, 7 warnings, 0.71s. Log: [passing-after.txt](passing-after.txt).

From `apps/web`:

```sh
npx playwright test e2e/release/ui-15.spec.ts --retries=0
```

Exit status 0. 14 passed, 25.9s. The spec is mocked. It checks that the page sends `page`, `page_size`, `sort`, and `order`, that the size line follows `max_upload_bytes`, that retry uses the job on the row, and that the page control clears the selection.

## CI

`build` and `web-release-e2e` run IDs are recorded in [ci-runs.md](ci-runs.md) after they succeed on push and pull_request.
