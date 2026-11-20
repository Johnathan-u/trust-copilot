# TC-07-011b: named log-redaction test

The named release test checks that a synthetic filename, reset link, cookie, and source sentence stay out of the upload rejection logs, the classification failure logs, the password-reset warnings, the formatted application log, and the Sentry event. It requires `request_id` and `job_id` on the records that carry them. This note does not accept TC-07-011 or TC-07-011b.

## Red command

Working directory `apps/api`. The test file was the one in this commit. Upload warnings and classification failure logs were restored from `4b89c925a6b628ac9b74f051c2e4870b4a4d5296` (the parent of TC-07-011a) for this run only. `scrub_sentry_event` for this run was that commit's Sentry `before_send`: drop cookies and the Authorization header, then return the event. `JsonFormatter` and `redact` were that same commit. Those working-tree edits are not in this commit. `app/main.py` and the auth routes stayed on master `265a268c750287f2cf347f95cb4c695c9645ae5d`.

```text
/tmp/tc-venv/bin/python -m pytest tests/release/test_log_redaction.py -q --tb=short
```

- Python 3.12.3, pytest 9.1.1
- This test opens no database

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 1 failed, 0.69s |

The failure is the four canaries. The upload warnings include the filename. The classification warnings include the source sentence. The Sentry event still has the filename, the source sentence, the cookie, and the reset link. The formatted application line already masks the cookie and the reset link, and it keeps `request_id` and `job_id`. The password-reset warnings do not include the reset link. The id checks ran before the canary check and passed. Log: `failing-before.txt`.

## Green command

Same interpreter and the same test. Product code is master `265a268c750287f2cf347f95cb4c695c9645ae5d`, which includes TC-07-011a (`15c6da10`).

```text
/tmp/tc-venv/bin/python -m pytest tests/release/test_log_redaction.py -q --tb=short
```

| Command | Exit | Total |
|---|---|---|
| the green command above | 0 | 1 passed, 0.64s |

Log: `passing-after.txt`. Pytest did not report a skipped test.

## Related suites

Same interpreter. PostgreSQL 16.15, pgvector 0.6.0, database `trustcopilot_test` at `127.0.0.1:5432`.

```text
/tmp/tc-venv/bin/python -m pytest tests/test_tc07011a_upload_log_redaction.py tests/release/test_log_redaction.py tests/test_upload_parse_review.py tests/release/test_upload_enqueue_conflict.py tests/release/test_secret_inventory.py::test_log_redaction_masks_cookies_tokens_and_url_credentials -q --tb=line
```

| Suite | Result |
|---|---|
| `tests/test_tc07011a_upload_log_redaction.py` | 3 passed |
| `tests/release/test_log_redaction.py` | 1 passed |
| `tests/test_upload_parse_review.py` | 1 passed |
| `tests/release/test_upload_enqueue_conflict.py` | 17 passed |
| `tests/release/test_secret_inventory.py::test_log_redaction_masks_cookies_tokens_and_url_credentials` | 1 passed |
| combined | 23 passed, 15 warnings, exit 0, 4.08s |

Auth routes were not edited. The named test calls the password-reset warning path. The broader auth suite was not run. This file does not record a CI run id.
