# TC-03-001 acceptance evidence

Commit under test: `e037a2f10b490ab96746305d57d26abba61571c5` (branch tc/platform/TC-03-001, stacked on tc/platform/TC-07-001). See environment.txt and commands.md for the commands, exit codes and totals.

* release_test.log: tests/release/test_config_contract.py. This is the AC1/AC2 gate: 333 passed, with no skips.
* related_existing_tests.log: the TC-07-001 release test plus the auth, session, CSRF, MFA, Slack and credential-store tests. `TestCredentialStoreService` was deselected because it needs Postgres. It is environment-blocked and fails identically on baseline.
* scan_tree.json and scan_history.json: scanner output with locations, rule IDs and kinds only. **They contain no values.** The tree has 0 block findings.
* full_suite_comparison.txt: whole suite, baseline vs branch. There are no new failures.
* CI was not run because this agent has no push credentials; the branch is delivered as a local commit and patch. Master CI is red per the Coordinator, and a separate CI-repair PR is pending.
* Docker images were not built because Docker is not available. The entrypoint, Dockerfile, compose and .dockerignore changes are verified statically by the release tests.
* There is no reviewer sign-off yet (DoD 5).
