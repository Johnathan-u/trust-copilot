# TC-07-011a: upload log redaction

The upload rejection warnings used to interpolate the user filename. The test uploads a file named `TC07011A-CANARY-filename-do-not-log` and asserts that the name is absent from the log records. This note does not accept TC-07-011 or TC-07-011a.

## Red command

Working directory `apps/api`. The new test was in the tree. The log lines still included `filename=`.

```text
/tmp/tc-venv/bin/python -m pytest tests/test_tc07011a_upload_log_redaction.py -q --tb=short
```

Base `4b89c925a6b628ac9b74f051c2e4870b4a4d5296`. The red run is the uncommitted upload test on that base, before the product change. At that point the file contained only `test_upload_logs_omit_the_user_filename`.

- Python 3.12.3, pytest 9.1.1

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 1 failed, 0.20s |

The failure is the canary filename in all four `upload_rejected` warnings, including the formatted message, the log args, and the JSON line. `request_id` was already on the JSON line. Log: `failing-before.txt`.

## Green command

Same interpreter and the same test file after the product change. The file then also covers classification failure logs and `scrub_sentry_event`.

```text
/tmp/tc-venv/bin/python -m pytest tests/test_tc07011a_upload_log_redaction.py -q --tb=short
```

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 3 passed, 0.40s |

Log: `passing-after.txt`. Pytest did not report a skipped test.

The same interpreter also ran the upload tests and the existing log-redaction test against PostgreSQL 16.15, pgvector 0.6.0, database `trustcopilot_test` at `127.0.0.1:5432`: `tests/test_tc07011a_upload_log_redaction.py`, `tests/test_upload_parse_review.py`, `tests/release/test_upload_enqueue_conflict.py`, and `tests/release/test_secret_inventory.py::test_log_redaction_masks_cookies_tokens_and_url_credentials`. Result: 22 passed, 15 warnings, exit 0.

`tests/release` on that database: 5389 passed, 19 skipped, 15 failed, exit 1, 530.94s. Three of those failures were this test file assigning a high-entropy literal to a variable whose name contained `TOKEN`. That assignment was renamed. The secret-inventory and safe-collection checks then passed (7 passed with the module). The other 12 failures are the local web toolchain (Node v22.23.4, no `apps/web/node_modules`). This file does not record a CI run id.
