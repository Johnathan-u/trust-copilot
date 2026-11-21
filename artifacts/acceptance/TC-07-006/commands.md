# TC-07-006 commands

Working directory for the API command: `apps/api`.

Red command, on base `ba789896951bc60e8f67842c87f67a0b50fbe988`, with only `tests/release/test_upload_stream.py` added. The product code was still master's unbounded `file.file.read()`.

```text
/tmp/tc-venv/bin/python -m pytest tests/release/test_upload_stream.py -q --tb=short
```

Exit 1. 8 failed, 15 passed, 10 warnings, 2.45s. Log: `failing-before.txt`.

ruff format later moved the four assertion lines in that log up by 2. The assertions are the same. The failures are: no Caddy `request_body`, no `read_bounded_upload`, an unbounded `read()` (`n` was -1), a 55-byte drain of a 32-byte cap, and document and questionnaire HTTP uploads that still issued an unbounded read. Trust intake's existing `read(max + 1)` already stayed within `limit + 1`, so that HTTP case passed on the base. The file as a whole failed.

Green command, same interpreter, after the product change:

```text
/tmp/tc-venv/bin/python -m pytest tests/release/test_upload_stream.py -q --tb=short
```

Exit 0. 23 passed, 10 warnings, 2.35s. Log: `passing-after.txt`. Pytest did not report a skipped test.

Web unit test, from `apps/web` (Node v22.23.4):

```text
npx vitest run tests/unit/api-proxy.test.ts
```

Exit 0. 8 passed. The file had 5 tests before this change.

Also run from `apps/api` after the change, same interpreter and database: `tests/release/test_upload_stream.py`, `tests/test_tc07011a_upload_log_redaction.py`, `tests/release/test_workbook_preflight.py`. 38 passed, exit 0.

Green run tree: `7e6bec9a511c94e80b57d16533200499d537695d`.

This file does not record a CI run id.
