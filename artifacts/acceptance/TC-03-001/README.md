# TC-03-001 acceptance evidence

Commit under test: `d27b544fd56b53c1f800b4bc5f2e12eba9fc99f6` (branch tc/platform/TC-03-001, stacked on tc/platform/TC-07-001). This includes the Coordinator ruling that SMTP is conditional on email delivery. See environment.txt and commands.md for the commands, exit codes and totals.

* release_test.log: tests/release/test_config_contract.py. This is the AC1/AC2 gate: 363 passed, with no skips. It includes the email-delivery tests:
  * production with email disabled and no SMTP boots;
  * production with email enabled and SMTP missing fails;
  * production with email enabled and valid SMTP passes.
* related_existing_tests.log: the TC-07-001 release test plus the auth, session, CSRF, MFA, login-email, Slack and credential-store tests. `TestCredentialStoreService` was deselected because it needs Postgres. It is environment-blocked and fails identically on baseline.
* scan_tree.json and scan_history.json: scanner output with locations, rule IDs and kinds only. **They contain no values.** The tree has 0 block findings.
* full_suite_comparison.txt: whole suite, baseline vs branch. There are no new failures.
* CI status is on PR #14. This agent did not run CI. Master CI is red per the Coordinator, and a separate CI-repair PR is pending.
* Docker images were not built because Docker is not available. The entrypoint, Dockerfile, compose and .dockerignore changes are verified statically by the release tests.
* There is no reviewer sign-off yet (DoD 5). Rotation (TC-07-001 AC2) and any history rewrite are owner actions and were not performed.
