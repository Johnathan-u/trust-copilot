# TC-17-004 acceptance in progress

Regression commit `e26f8284dbb7f02b9b673da5f5456e6edbb62fc9` was tested by [CI run 40922365521](https://github.com/Johnathan-u/trust-copilot/actions/runs/40922365521): **14 failed, 3194 passed, 1 skipped**. The skip is the external blind pack; the failures were the new FAQ lifecycle, source/scope, action and schema cases. Migration, lint, safe collection, pre-commit and web-release-e2e passed. The regression commit intentionally preceded implementation.

The current implementation adds content snapshots, same-workspace source references, explicit human review and publication, durable create retry, source-change invalidation, and current membership/role checks. New fixtures restore FAQ, source/history, evidence, audit, idempotency, API-key, membership, user and workspace counts. Rollback archives are asserted absent after re-upgrade; no trigger/FK bypass is used.

Local locked Python 3.12 results: 13 schema/head checks passed, scoped Ruff passed, all 3277 tests collected. Alembic offline SQL compiled after the pure master merge and separate parent update to `tc10001_job_leases`. Local PostgreSQL is unavailable, so PostgreSQL migration, concurrency and API assertions remain **unverified at the implementation SHA** until CI runs the full suite. The added DB cases cover non-default rollback round-trip, edits while downgraded, parent workspace changes, concurrent source limits, failure rollback and stale-session mutations.

The shared `security_page_service` caller still needs the Coordinator's allocation to consume the published-only projection. No full ticket completion is claimed while that caller remains unchanged, migration landing is pending, and exact-head PostgreSQL CI is outstanding. The API assignment does not qualify a new browser editor.

No new dependency, live provider or account call is used. TC Coordinator alone merges.

Independent reviewer `/root/tc_codex_integrations/response_limit_review` found a stale-support gap for replaced Document content. The fix adds parent document identity to the approval digest and shared document locks during review/publication. The reviewer inspected that fix, independently passed the 13 pure tests, and reported no remaining Critical/Important issue in the allocated code. PostgreSQL execution of the new regression remains pending.
