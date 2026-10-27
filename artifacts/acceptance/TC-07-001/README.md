# TC-07-001 acceptance evidence

Commit under test: `c3243257a8ba3a44f962c4a461de5295535106df` (branch tc/platform/TC-07-001). See environment.txt, commands.md (commands, exit codes, totals).

* release_test.log — tests/release/test_secret_inventory.py (AC1 regression gate).
* related_existing_tests.log — auth/session/CSRF/MFA/Slack/credential-store tests. `TestCredentialStoreService` deselected: needs Postgres (environment-blocked; fails identically on baseline).
* scan_tree.json / scan_history.json — scanner output: locations, rule IDs, kinds only; **no values**.
* full_suite_comparison.txt — whole-suite baseline vs branch.
* CI: not run — no push credentials for this agent (branch delivered as bundle/patch). Master CI is red per Coordinator; a separate CI-repair PR is pending.
* AC2 (rotation, reuse verification): owner action, not performed — see docs/release/tickets/TC-07-001.md.
