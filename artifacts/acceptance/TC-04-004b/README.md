# TC-04-004b local implementation evidence

Claim: [#85 comment 6514687779](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514687779).
Implementation base: `a97b947454b63d849097207b5f79a01323b06d3a`.
Branch: `codex/TC-04-004b-current-session-policy`. Exact implementation commit/tree are returned to the coordinator; no worker publication occurs.

Commands ran from `apps/api` using `/tmp/tc-backend-venv/bin/python` and `/tmp/tc-backend-venv/bin/ruff`: Python 3.12.14, FastAPI 0.162.0, SQLAlchemy 2.0.55, pytest 9.1.1, Ruff 0.5.6, httpx 0.28.1. No dependency or existing fixture changes.

| Check                                                                                                           | Actual result                                                                  |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Initial `python -m pytest tests/release/test_remember_policy.py -k 'not postgres' -q` against unchanged runtime | 23 failed / 12 passed / 35 deselected; exit 1                                  |
| Same 35 local cases after runtime repair                                                                        | 35 passed / 35 deselected; exit 0                                              |
| Final related command below, including review regressions                                                       | 139 passed / 119 deselected; exit 0, including all 42 final local policy cases |
| Final new-file `--collect-only -q`                                                                              | 84 cases: 42 SQLite and 42 PostgreSQL                                          |
| `TC_REQUIRE_DB=1 python -m pytest -q`                                                                           | Exit 3 before execution: local PostgreSQL connection refused on port 5432      |
| Final unit command below                                                                                        | 714 passed / 11 existing skips / 3354 deselected; exit 0                       |
| Ruff check/format, compileall on four changed Python files; `git diff --check`                                  | Passed                                                                         |

```sh
python -m pytest tests/release/test_remember_policy.py tests/release/test_session_validation.py tests/release/test_principal_contract.py tests/release/test_mfa_reenrol_security.py tests/release/test_session_signing_key_migration.py tests/release/test_key_rotation.py -q -k 'not postgres and not fresh_database and not reencrypts and not resumes_from and not mfa_reenrol_when and not failures_are_audited and not helper_audits and not retired_session_rows'

env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy python -m pytest -m unit -q
```

The first broad unit attempt caught a synthetic password literal through `test_safe_collection.py::test_no_signing_literal_by_scanner[tests]` (1 failed / 748 passed / 46 skipped). The test now generates its password at runtime; the unchanged scanner passes. The new database suite is explicitly integration-marked instead of being incorrectly inferred as unit through an imported fixture. The final unit result above is authoritative.

The negative control reproduces the 30-day remembered lifetime exceeding one-day/default policy, stale policy acceptance, missing/future timestamps, expiry-boundary acceptance, target-workspace expiry renewal and policy-query failure granting access. Real password/MFA issuance and post-policy-change requests are tested against real stored rows. Stored creation times are deliberately aged to simulate elapsed time; no wall-clock wait is claimed. Added controls isolate target-policy lookup failure and prove an older session remains valid under a legitimate longer tenant limit. Failed reads, switches and issuance assert unchanged full rows. Original owned-user/workspace/session cleanup remains exact, with external full rows additionally compared before/after each case.

Limitations: SQLite is not PostgreSQL release qualification. The strict whole-suite run could not execute; all PostgreSQL counterparts, actual final-head CI and independent review remain required. No real provider, browser, production application lifespan, idle-timeout or persisted remember-choice qualification is claimed. Landed #127 is integrated by the separate pure merge `5f9dad0b4cf60f3dba7d4f4a0d61dcf50b9be08d`; full parent TC-04-004/TC-04-006 gates remain open.

Independent-review repair, scope extension [#85 comment 6514900298](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514900298):

- Review base: `5f9dad0b4cf60f3dba7d4f4a0d61dcf50b9be08d`. A relative age computed before signing could extend the absolute deadline when the signer's clock advanced. The signer now accepts the established absolute expiry without changing token claims or verification; switching checks the deadline again after signing before acknowledging success.
- Pending MFA confirmation previously performed its second, fallible policy read after committing factor/session/recovery-code mutations. That read now precedes all enrollment-state mutation/consumption. The failed attempt leaves every row and the cookie unchanged; the same enrollment can then retry and receive ten unique recovery codes and a new valid session.
- `python -m pytest tests/release/test_remember_policy.py -q -k 'not postgres and (clock_advances or pending_mfa_policy_failure)'`: corrected controls against unchanged review-base runtime **5 failed / 79 deselected**, then repaired runtime **5 passed / 79 deselected**. Clock controls advance time before the real signer and cover original/target deadlines both before and after expiration; no sleep or mocked signer result is used. Policy failure is injected only on the second Workspace SELECT.
- Initial new-test setup needed two corrections before this counted red/green run: parse the quoted enrollment response cookie, and isolate the replacement cookie from the fixture's original domainless cookie. These harness failures are not counted as product reproduction. Original assertions and all earlier test cases remain intact.
- Final related selection **139 passed / 119 deselected**; final broad unit **714 passed / 11 skipped / 3354 deselected**; all 84 policy cases collect; Ruff/format/compileall/diff checks pass. PostgreSQL remains unavailable locally; its 42 counterparts require actual CI.

CI cookie-helper repair, recovery claim
[#85 comment 6515297056](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515297056):

- Repair base: published `5ede7b6cd476965ef0b1ed36ef2d80e6ad862427` in a fresh
  `codex/TC-04-004b-cookie-helper-repair` worktree. The restored runtime had no
  backend environment; the existing hash-locked requirements restored it without
  dependency or repository lock changes.
- Actual push [run 41003527180, job 123893133838](https://github.com/Johnathan-u/trust-copilot/actions/runs/41003527180/job/123893133838)
  reported 14 failures, 4064 passes and one skip. The failing policy cases reached
  `current_row` after real login; direct verification of the HTTPX jar's quoted
  cookie returned `None`. Parsed response-cookie verification and expiry assertions
  had passed. This is a test-helper defect, not evidence that the runtime accepts
  invalid signed cookies.
- A local real-HTTP/stored-SQLite probe varied the owned user's email length across
  three values. One produced an unquoted cookie and two produced quoted cookies.
  All three authenticated `/api/auth/me` and verified the parsed response token;
  the old helper failed only for the two quoted values. No credential is retained
  in this evidence.
- Two explicit real-login encoding regressions per backend reproduce both forms.
  Before the helper repair, SQLite returned **1 failed / 1 passed**; the quoted
  case raised the same `NoneType` error as CI. The helper now uses the existing
  `SimpleCookie` parser before the unchanged `verify_token`, matching the existing
  response-cookie handling. Every earlier assertion and production file remains
  unchanged. The suite now has 88 cases, 44 per backend.
- Final repair verification and remaining PostgreSQL/CI gates are recorded in
  [verification.txt](verification.txt). The prior local results above remain
  historical evidence; they do not qualify the repaired head's PostgreSQL cases.
