# TC-17-003 acceptance evidence

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

Independent review: **pending**. The implementer (Claude) can't accept this ticket.
