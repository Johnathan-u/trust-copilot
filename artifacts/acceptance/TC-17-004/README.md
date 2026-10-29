# TC-17-004 acceptance in progress

Regression commit `e26f8284dbb7f02b9b673da5f5456e6edbb62fc9` was tested by [CI run 40922365521](https://github.com/Johnathan-u/trust-copilot/actions/runs/40922365521): **14 failed, 3194 passed, 1 skipped**. The skip is the external blind pack; the failures were the new FAQ lifecycle, source/scope, action and schema cases. Migration, lint, safe collection, pre-commit and web-release-e2e passed. The regression commit intentionally preceded implementation.

The current implementation adds content snapshots, same-workspace source references, explicit human review and publication, durable create retry, source-change invalidation, and current membership/role checks. New fixtures restore FAQ, source/history, evidence, audit, idempotency, API-key, membership, user and workspace counts. Rollback archives are asserted absent after re-upgrade; no trigger/FK bypass is used.

Local locked Python 3.12 results: 13 schema/head checks passed, scoped Ruff passed, all 3277 tests collected. Alembic offline SQL compiled after the pure master merge and separate parent update to `tc10001_job_leases`. Local PostgreSQL is unavailable, so PostgreSQL migration, concurrency and API assertions remain **unverified at the implementation SHA** until CI runs the full suite. The added DB cases cover non-default rollback round-trip, edits while downgraded, parent workspace changes, concurrent source limits, failure rollback and stale-session mutations.

Coordinator ruling [6504557554](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504557554) approved the sole shared-service change: `get_public_security_page` now consumes `list_published_faqs`. No other line of that service changed. No full ticket completion is claimed while exact-head PostgreSQL CI and migration landing remain outstanding. The API assignment does not qualify a new browser editor.

No new dependency, live provider or account call is used. TC Coordinator alone merges.

Independent reviewer `/root/tc_codex_integrations/response_limit_review` found a stale-support gap for replaced Document content. The fix adds parent document identity to the approval digest and shared document locks during review/publication. The reviewer inspected that fix, independently passed the 13 pure tests, and reported no remaining Critical/Important issue in the allocated code. PostgreSQL execution of the new regression remains pending.

## Public caller follow-up

Prior implementation branch head `e57d44f0aca42e6eff662e9a7a9d6878436808f4` passed PR validation in [run 40926571931](https://github.com/Johnathan-u/trust-copilot/actions/runs/40926571931): 3282 backend tests passed, one external-data skip, and build/web-release-e2e succeeded. GitHub checked out synthetic merge `8388550` against master `d9ab8b6`; this is not evidence for the later caller change.

Test-first checkpoint `1f3a42d226200fd8bed6d272e0e2f4ee6f73b72b` preserves the current-custom-role and unavailable-document regressions and adds the real public-route test. All 76 FAQ cases collected; the local full suite collected 3281 tests. The different count from the prior PR run reflects that run's newer merged target. Thirteen schema/head checks passed locally, with one existing Alembic configuration deprecation warning. PostgreSQL is unavailable locally.

A controlled local caller probe returned draft, template and withdrawn content before the one-line correction (assertion failure), then returned only the reviewed publication after it (exit 0). That probe isolates caller selection with controlled service outputs; it is not database acceptance. The committed PostgreSQL route test exercises actual persisted lifecycle/source state and GET read-only behavior in CI. Scoped Ruff check/format and `git diff --check` passed. Final exact-head CI remains pending for this follow-up.

Backend independent review accepted the caller and new route regression, and identified the legacy security-page test that expected seeded templates to appear publicly. That expectation now requires an empty publication list. The four service cases use an isolated workspace with FAQ/source/history cleanup and baseline count assertions; the real domain test covers the positive public item shape. Both related modules collect 82 cases locally. No additional service behavior changed.
