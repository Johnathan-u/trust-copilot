# TC-07-001 acceptance evidence

Commit under test: `a925858143f30fc2e2b61ef3e27999a3107def9a` (branch tc/platform/TC-07-001). See environment.txt, commands.md (commands, exit codes, totals).

* release_test.log: tests/release/test_secret_inventory.py (AC1 regression gate plus deploy-doc guidance checks), 67 passed.
* related_existing_tests.log: auth/session/CSRF/MFA/Slack/credential-store tests, 41 passed, 89 skipped, 7 deselected. `TestCredentialStoreService` is deselected because it needs Postgres (environment-blocked; fails identically on baseline).
* scan_tree.json / scan_history.json: scanner output with locations, rule IDs and kinds only; **no values**. Tree: 0 block, 26 review. History (all local refs): 142 block (unchanged; history not rewritten), 98 review (+15 vs the previous run, all review-class: new blob versions of .env.example/config.py dev defaults and test_config_contract.py from the stacked TC-03-001 branch ref).
* full_suite_comparison.txt: whole-suite baseline vs branch, 0 new failures.
* CI: not run. This agent has no push credentials (delivered as a bundle). Master CI is red per the Coordinator; a separate CI-repair PR is pending.
* **AC2: "No live deployment; owner statement 2026-10-27, relayed by the Coordinator. All exposed values are retired and must never be reused."** Engineering did not rotate, test or use any exposed value. The deploy docs (README.md Production secrets, .env.example header, docker-compose.prod.yml header) require operator-generated secrets (e.g. `openssl rand`) and state that the old values are retired. These are enforced by `test_deploy_entrypoints_require_operator_generated_secrets` and `test_deploy_docs_never_point_at_committed_values`. Production startup enforcement is TC-03-001's config contract. **Open owner closing item: git-history rewrite** (not done by engineering).
* Planning deviation: E01/TC-01-001 was ruled non-blocking by the Coordinator.
