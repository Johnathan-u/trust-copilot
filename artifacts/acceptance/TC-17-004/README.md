# TC-17-004 acceptance in progress

## Foreign document fixture CI repair — 2026-10-30

Claim: #85 comment6511660571. Repair base:
`cd74f998798cad454a594428ab342671855e1d49`, preserving the existing PR #91 history.
The pull-request backend job `123806833622` reproduced one failure:
`test_missing_and_unavailable_document_sources_are_equal_404[foreign]`.
Its fixture attempted `UPDATE documents SET workspace_id=...` while local
evidence still referenced that document. The existing `tc_parent_ws_documents`
trigger correctly raised `CheckViolation: parent workspace move rejected`
before the HTTP assertions. That job reported **3625 passed, 1 failed, 1 skipped**;
the skip was the external blind pack.

The fixture now creates a document in the foreign workspace and attaches that
workspace's evidence to it, then submits the foreign evidence ID from the local
admin session. The deleted-document case still uses local evidence and a local
document that is subsequently soft-deleted. Both cases retain the equal HTTP 404
status and identical JSON assertions against a nonexistent evidence ID. No
database guard, product code, migration, mock or acceptance assertion changed.
Existing parent-workspace and cross-workspace constraint regressions remain intact.

Local Python 3.12 checks on the repaired test content:

- FAQ schema/head checks: **13 passed, 63 deselected**, with one existing Alembic
  `path_separator` deprecation warning.
- FAQ, parent-workspace, cross-workspace and security-page modules: **124 tests
  collected**.
- Scoped Ruff check/format and `git diff --check`: passed.
- A strict targeted database run before the repair and the full strict suite
  command after it both exited **3 during setup**: connection to
  `127.0.0.1:5432` refused. No local PostgreSQL execution or database pass is
  claimed. Docker/PostgreSQL executables are unavailable in this workspace.

Commands from `apps/api` (using `/tmp/tc-backend-venv/bin/python`):

```sh
python -m pytest tests/release/test_domain_security_faq.py -q -k 'schema_rejects or revision_is_on_single_head_chain'
python -m pytest --collect-only -q tests/release/test_domain_security_faq.py tests/release/test_parent_workspace_move.py tests/release/test_cross_workspace_refs.py tests/test_security_page.py
python -m ruff check tests/release/test_domain_security_faq.py
python -m ruff format --check tests/release/test_domain_security_faq.py
git diff --check
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest 'tests/release/test_domain_security_faq.py::test_missing_and_unavailable_document_sources_are_equal_404[foreign]' -q
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest -rs
```

Independent review and fresh push/pull-request build plus web-release-e2e results
for the published repair head remain required. The coordinator records the final
commit/tree mapping and CI results in #85 and the PR; earlier green browser jobs
do not qualify this repair head.

## Continuation — 2026-10-30

Claim: #85 comment6511380086. Prior head `3ff096949fccca25ac58cd003f1191749d26c0aa` is preserved. Pure merge `daa725a922d987a914ecb0d3724986e9625f1bcc` has parents `3ff0969` and actual master `499f8af`; tree `0c434e6b7de74151b02231823553fbaaa810e5e8` exactly matches automatic `git merge-tree`, with no conflict or manual product edits. The separate parent update changes only `tc17004_faq_review.down_revision` to the landed `tc18001_reviewed_replies`, plus these evidence/ticket records.

On the resulting tree, 13 schema/head checks passed (63 DB cases deselected), scoped Ruff and formatting passed, and Alembic reports the single head `tc17004_faq_review`. The targeted offline upgrade `tc18001_reviewed_replies:tc17004_faq_review --sql` compiled successfully (129 lines). A full-history offline attempt stops in existing migration038's data-dependent `.mappings()` call; it does not qualify the full chain. No local PostgreSQL or browser execution is claimed. Final published-head push and pull_request build plus web-release-e2e, including real database round trips, remain required. Local/published commit and tree mapping will be recorded by the coordinator in #85 and the PR.

Commands:

```sh
python -m pytest tests/release/test_domain_security_faq.py -q -k 'schema_rejects or revision_is_on_single_head_chain'
python -m alembic heads
python -m alembic upgrade tc18001_reviewed_replies:tc17004_faq_review --sql
python -m ruff check alembic/versions/tc17004_faq_review.py
python -m ruff format --check alembic/versions/tc17004_faq_review.py
```

## Earlier evidence

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
