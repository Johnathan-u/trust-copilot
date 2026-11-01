# TC-17-003 acceptance evidence

## Final result (accepted)

- **Tested commit:** master `d4ba7340924f6f6e283c2c31a12048ac171b428d` (squash merge of PR #171, final head `207eb2e76c81893018ec46a5205736365e800e20`)
- **CI on the final PR head:** push [41327100445](https://github.com/Johnathan-u/trust-copilot/actions/runs/41327100445) and pull_request [41327104259](https://github.com/Johnathan-u/trust-copilot/actions/runs/41327104259). `build` and `web-release-e2e` were green.
- **CI on master after merge:** push [41328825686](https://github.com/Johnathan-u/trust-copilot/actions/runs/41328825686). `build` and `web-release-e2e` were green.
  - `alembic upgrade head` applied `tc23001_deal_types -> tc17003_security_claims`.
  - Web unit tests: 44 files passed.
  - `pytest -rs` (`TC_REQUIRE_DB=1`, PostgreSQL): **6136 passed, 1 skipped**. The skip is the documented `external_data` blind-pack test, which is unrelated.
  - All 25 tests in `tests/release/test_domain_security_page.py` passed.
- **Independent review:** a fresh reviewer agent (not the implementer) found 2 blockers in round 1, both fixed. It approved `207eb2e` in round 2: [review](https://github.com/Johnathan-u/trust-copilot/pull/171#issuecomment-6560988631).
  - Round-1 blocker: stale proof (a deleted document or expired evidence) still showed as attested.
  - Round-1 blocker: the downgrade/upgrade round trip and the failure-partway rollback were untested.
  - Non-blocking follow-ups are tracked as TC-17-003a (Jira SCRUM-504).

## History: first green head

- **Tested commit:** `4fc9f951cdd3cc28e21fd6398b8c099d18464b92` (branch `claude/TC-17-003-security-claims`, PR #171)
- **Environment:** GitHub Actions `ubuntu-latest`, the repository CI workflow (isolated pgvector PostgreSQL service, Python 3.11, Node 24.22.1)
- **CI runs:** push [41317469529](https://github.com/Johnathan-u/trust-copilot/actions/runs/41317469529) and pull_request [41317473280](https://github.com/Johnathan-u/trust-copilot/actions/runs/41317473280). `build` and `web-release-e2e` were green in both.

| Command (CI step) | Exit | Result |
|---|---|---|
| `alembic upgrade head` | 0 | `tc23001_deal_types -> tc17003_security_claims` applied |
| `ruff check .` (apps/api) | 0 | passed |
| `npm run lint`, `npm run format:check`, `npm run typecheck` (apps/web) | 0 | passed |
| `npm run test:unit` (apps/web) | 0 | 44 files passed, including `lib/securityPage.test.ts` (5 tests) |
| `pytest -rs` (apps/api, `TC_REQUIRE_DB=1`) | 0 | **6131 passed, 1 skipped** (the documented `external_data` blind-pack test, unrelated). Includes all 20 tests in `tests/release/test_domain_security_page.py` and the existing `tests/test_security_page.py` |
| Release Playwright specs (`web-release-e2e`) | 0 | passed |

The earlier head `6f5350b` failed only `npm run lint` (React Compiler `set-state-in-effect` on the page's mount effect). `4fc9f95` fixed it by setting state only in promise callbacks, as the demo-proof page does.

Local checks in the authoring session: Ruff (CI rule set) and Prettier passed, and the presenter was run in Node. The Python and web suites could not run locally because package installs are blocked in that session, so CI is the test of record.

Independent review: approved on the final head (see above). The implementer (Claude) did not accept its own work.
