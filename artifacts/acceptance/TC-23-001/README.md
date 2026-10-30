# TC-23-001: Typed scoped deals, rooms, and questionnaire links

Framework catalogs stay **BLOCKED** pending **TC-01-007**. Amounts in the tests are synthetic.

## PR #96 review repair (2026-10-30)

This repair builds on `a392f9358fc5f782150d3e262c8d7009fe9641cd`, preserving the original implementation. Assignment: [#85](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6512133723). Review blockers: [#96](https://github.com/Johnathan-u/trust-copilot/pull/96#issuecomment-6511935044). The repair commit and exact tree are returned to the coordinator for independent review; no publication or migration re-parenting is performed by this worker.

- Domain effects and the owner-fenced idempotency response now share one transaction. SQLite controls execute the real response writer and prove rollback on cache failure, stale ownership, and final commit failure. They also check one effect after retry. These are transaction controls, not PostgreSQL qualification.
- Downgrade stores exact typed snapshots before projection. Re-upgrade restores unchanged values by row/workspace/creation identity, preserves older-version edits, and validates current references. Partial/conflicted/unmatched snapshots remain recoverable with `restore_issue`; legacy float holds are durable and cannot replace corrected amounts.
- The consumer accepts legacy/CRM amounts with null currency. API create remains strict.
- Mixed or unknown currencies return null aggregates with additive reason/currency fields; one known currency retains exact Decimal sums, and the empty sum remains `0.00`. No exchange rates or conversion policy were added.

Local interpreter: `/tmp/tc-backend-venv/bin/python` (Python 3.12); web: Node 24.22.1. Locked web dependencies were copied from a sibling worktree after `package-lock.json` equality was verified.

| Check | Result |
| --- | --- |
| Before repair: `pytest tests/test_deal_integrity_controls.py -q` | 8 failed, reproducing committed domain effects on response failure, missing owner fencing, and unconditional currency sums |
| Before repair: `npx vitest run lib/dealConsumer.test.ts` | 2 failed / 3 passed, reproducing legacy currency and unavailable-total rejection |
| After repair: `pytest tests/test_deal_integrity_controls.py -q` | 9 passed, including an additional final-commit failure control |
| `pytest tests/test_deal_integrity_controls.py tests/release/test_domain_deals.py tests/release/test_deal_migration_recovery.py --collect-only -q` | 46 collected; collection does not qualify database behavior |
| `TC_REQUIRE_DB=1 pytest tests/release/test_domain_deals.py tests/release/test_deal_migration_recovery.py -q` | Blocked before test execution: PostgreSQL connection refused on localhost:5432 |
| Alembic `upgrade tc10001_job_leases:tc23001_deal_types --sql` and reverse `downgrade ... --sql` | Both rendered successfully; offline rendering does not execute PostgreSQL SQL |
| Ruff check/format check and Python compileall on the six changed Python files | Passed |
| `npm run typecheck` | Passed |
| `npm run lint` and `npm run format:check` (also focused checks on both consumer files) | Passed |
| `npm run test:unit` | 27 files, 175 tests passed |

`test_domain_deals.py` adds actual PostgreSQL response-failure/reclaimed-owner and mixed/unknown-currency route regressions, preserving existing permissions, tenant/ref, create, and legacy round-trip checks. `test_deal_migration_recovery.py` defines 12 real PostgreSQL cases: corrected held legacy amounts; exact large/max new typed values and all added fields across two cycles; real writes in the downgraded parent schema plus newly inserted rows; archive preservation across later cycles; unavailable/malformed/foreign refs; deletion, changed workspace, and reused row ids. Synthetic rows and their recovery records are cleaned up explicitly. Foreign archive references are negative restore fixtures backed by real foreign rows; no workspace constraints are disabled.

Remaining gates: execute the PostgreSQL cases, independently review the repair, merge current master and re-parent only after the reserved PR #93 migration actually lands, then require both push and pull-request `build`/`web-release-e2e` checks for the final exact head. The earlier evidence below belongs to the original implementation and does not qualify this repair.

## Original implementation command

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

## Landing integration, 2026-10-30

After #93 landed at `2ce464d7cbdcc25c336714cb1b642c8d8cb396d7`, pure merge
`603e4b1deb6d3a33e35bff448646bc8c249523be` incorporated that master without
conflicts. A separate parent change now points `tc23001_deal_types` at the actual
landed `tc07002_session_key_id`. Earlier parent references above are historical.

From `apps/api`, `/tmp/tc-backend-venv/bin/alembic heads` reports only
`tc23001_deal_types`. Targeted `alembic upgrade
tc07002_session_key_id:tc23001_deal_types --sql` and the reverse `downgrade --sql`
both render transactionally. `python -m pytest
tests/test_deal_integrity_controls.py -q` passes all nine controls after the
merge (five existing Python 3.12 datetime-adapter warnings).

This is offline/local integration evidence, not PostgreSQL execution. Independent
integration review and exact final-head push/pull-request build and browser jobs
remain required; the non-default archive round trips must execute in CI.
