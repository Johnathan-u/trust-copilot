# TC-16-006 gap 1: flag changes are audited, and production env vars do not override rows

This note does not accept TC-16-006. No migration. No run ids. Gap 2 remains open:
nothing asserts that a flag cannot turn off CSRF, session checks, or audit, and the
build does not fail when an advertised feature is flagged off.

Batch 7 on master `08443a69` ran `python3 -m pytest tests/test_feature_flags.py -q`
and recorded 17 passed. `tests/release/test_feature_flags.py` was not in that tree.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. Product code was
`08443a69`. The new tests were present. The audit write and the production resolution
were not.

```text
python -m pytest tests/release/test_feature_flags.py tests/test_feature_flags.py -q --tb=line
```

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15, database `trustcopilot_test` on localhost

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 7 failed, 22 passed, 12 warnings, 2.56s |

A flag change wrote no audit event (`assert 0 == 2`). `set_flag` rejected `actor_user_id`.
With `FEATURE_CONNECTORS_AWS=1`, `is_enabled` stayed true for a row stored as false when
`APP_ENV` was production, including ` Production ` and `PRODUCTION`. The same assertion
failed in `test_env_override_takes_precedence`. The non-admin 403, the rejected name, the
production default when no row exists, and the override in development, test, and staging
passed on that code. Log: `failing-before.txt`.

## SHA

The green tests ran on `0c8e9615df4b63f9295265b520b4dedb14e170c0`. The commit that adds
this directory does not change the code under test.

## Green command

Same interpreter, after the audit write and the production resolution.

```text
python -m pytest tests/release/test_feature_flags.py -q --tb=short
python -m pytest tests/test_feature_flags.py -q --tb=short
```

## Environment

- Python 3.12.3, pytest 9.1.1
- PostgreSQL 16.15, database `trustcopilot_test` on localhost

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_feature_flags.py -q --tb=short` | 0 | 12 passed, 15 warnings, 1.90s |
| `python -m pytest tests/test_feature_flags.py -q --tb=short` | 0 | 17 passed, 18 warnings, 2.13s |

Pytest did not report a skipped test. Log: `passing-after.txt`.

Before this change the unit file was 17 passed. It is still 17 passed.
`test_env_override_takes_precedence` now expects the override only when `APP_ENV` is
development, and expects the stored row to win when `APP_ENV` is production. The release
file is 12 new tests.

## What was not run here

The full `pytest -rs` suite and the CI `build` and `web-release-e2e` jobs are not in
this directory. This file does not record run ids.
