# TC-03-001 acceptance evidence

Commit under test: `7382066fef77eaa39788b074388489c3e819d67f` (branch tc/platform/TC-03-001, stacked on tc/platform/TC-07-001). This includes the Coordinator ruling that SMTP is conditional on email delivery, and the merge of tc/platform/TC-07-001 at a9088d7 (AC2 owner statement and operator-generated-secrets deploy docs; merge commit 9287533, `.env.example` header conflict resolved by keeping both headers). See environment.txt and commands.md for the commands, exit codes and totals.

* release_test.log: tests/release/test_config_contract.py. This is the AC1/AC2 gate: 363 passed, with no skips. It includes the email-delivery tests:
  * production with email disabled and no SMTP boots;
  * production with email enabled and SMTP missing fails;
  * production with email enabled and valid SMTP passes.
* related_existing_tests.log: 108 passed, 89 skipped, 7 deselected. This is the TC-07-001 release test (now with the deploy-doc guidance checks) plus the auth, session, CSRF, MFA, login-email, Slack and credential-store tests. `TestCredentialStoreService` was deselected because it needs Postgres. It is environment-blocked and fails identically on baseline.
* scan_tree.json and scan_history.json: scanner output with locations, rule IDs and kinds only. **They contain no values.** Tree: 0 block, 30 review. History (all local refs): 142 block (pre-existing, not rewritten), 98 review.
* full_suite_comparison.txt: whole suite, baseline vs branch. 241 failed, 715 passed, 735 skipped, 31 errors; 0 new failures.
* CI status is on PR #14. This agent did not run CI. Master CI is red per the Coordinator, and a separate CI-repair PR is pending.
* Docker images were not built because Docker is not available. The entrypoint, Dockerfile, compose and .dockerignore changes are verified statically by the release tests.
* There is no reviewer sign-off yet (DoD 5). TC-07-001 AC2 is recorded as: "No live deployment; owner statement 2026-10-27, relayed by the Coordinator. All exposed values are retired and must never be reused." The git-history rewrite is still an open owner closing item and was not performed.
* Planning deviation: E01/TC-01-001 was ruled non-blocking by the Coordinator.

## Refresh after merging master f7468ff (no rebase)

* The notes above describe the pre-merge commit and are kept for history. Where they conflict with this section, this section is authoritative.
* release_test.log has been regenerated at the post-merge head: tests/release/test_config_contract.py, 456 passed, no skips. Production detection comes from master's `is_production_env()`. Every credential shipped in `.env.example`, including the dev S3/MinIO pair, is refused in production with an error that names the variable but never its value.
* Full CI mirror (fresh digest-pinned pgvector pg16, TC_REQUIRE_DB=1): every step exits 0. The results are in the PR body. Master's secret scanner finds 0 block on the tree and on the added lines. The new review-level hits are synthetic test fixtures generated at runtime.
