# TC-23-001: Typed scoped deals, rooms, and questionnaire links

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Amounts in the tests are synthetic.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. Database `trustcopilot_test` on PostgreSQL 16.15.

```text
python -m pytest tests/release -q
```

Web, from `apps/web`, Node 24:

```text
npx vitest run
```

## SHA

Tests ran on `fd5221e9b429da14a974d5177a120061fc348480`. That commit is the pure merge of `cf8048a` and `d9ab8b6`. Its tree matches `git merge-tree --write-tree`. This file was added after that commit and does not change the code under test.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `pytest tests/release -q` | 0 after one quota rerun | 1820 passed in the full run; 1 failed on an accumulated `ai_jobs` hourly counter, then passed alone |
| `npx vitest run` | 0 | 27 files, 173 passed |

`test_domain_deals.py` is 21 of the release results. The full-run failure was `test_replay_returns_same_error_body_as_live_response`: generate returned 429 because workspace 1's hourly AI job counter was already full from earlier local runs. Resetting that counter made the same test pass. It is not a deals assertion.

## Migration

`tc23001_deal_types` revises `tc10001_job_leases`. The round trip holds a non-representable float (`1/3`), checks the amount is null, restores that exact text on downgrade, and upgrades again. Deal and hold-table counts are asserted back to the start of every test in the file.


## Typecheck fix

CI build on `9730486` failed `tsc` in `dealConsumer.ts`: `owner_user_id`, `room_id`, and `win_rate` stayed `unknown`. The parser now assigns them from an explicit null or typed branch. `npm run typecheck` and `dealConsumer.test.ts` (3 passed) ran on `89af4f3df776ef5a5f7284a0f84a1dd152ff4cc8`.
