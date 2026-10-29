# TC-18-001 evidence

Backend logic at `b57cb9bb4154c645947681ba05c2bcf1da6ef194` has independent reviewer acceptance and all four exact-head CI checks GREEN. Sensitive SMTP integration is gated on #86 merging; frontend consumer qualification and migration landing-slot confirmation remain pending. This is not full-ticket completion.

## Executed verification

| Checkpoint | Evidence | Result |
|---|---|---|
| Initial regression branch `093d60612ae8f330a898cbecc816b05e141ea6c0` | [PR run40922233567](https://github.com/Johnathan-u/trust-copilot/actions/runs/40922233567), build job123618258154, tested merge `a426963` against76ae791 | 21 expected regression failures, 3198 passed, 1 external blind-pack skip; no setup errors. Web E2E passed. Companion push run40922225333 failed to start isolated Postgres, so is not a functional result. |
| First implementation `4750969cda02bd810f49854d02d27f5fc7019e33` | [PR run40924971232](https://github.com/Johnathan-u/trust-copilot/actions/runs/40924971232), build job123627929936, tested merge `9e53c4a` | 8 failed, 3269 passed, 1 external skip. New domain/migration cases passed. A legacy mocked guard failed before removing its override, causing7 downstream auth failures; the context-managed override fixes this. |
| Reviewed storage/context checkpoint `bcbb40fdd607e61a0b2377f555805a8d976d0b18` | [PR run40926595986](https://github.com/Johnathan-u/trust-copilot/actions/runs/40926595986), build job123633654168, tested merge `cb43d85` againstd9ab8b6 | **3288 passed, 1 external blind-pack skip**, no failures. Migrations, pre-commit, lint, collection, frontend typecheck/build/audit and web E2E passed. |
| Final reviewed code `b57cb9bb4154c645947681ba05c2bcf1da6ef194` | [PR run40930801921](https://github.com/Johnathan-u/trust-copilot/actions/runs/40930801921) and [push run40930762020](https://github.com/Johnathan-u/trust-copilot/actions/runs/40930762020); PR build123648387987 | **3294 passed, 1 external blind-pack skip**. Both build and both web-release-e2e jobs passed on this exact code SHA, including the commit-then-raise/replay regression. |

Latest local command, from `apps/api` using the shared locked Python3.12 runtime:

```sh
PYTHONPATH=. python -m pytest tests/test_trust_request_routing.py tests/release/test_domain_trust_requests.py -q -k 'schema or revision_reaches or TestResolveWorkspace or TestAttachment or TestToDict or abort_failure or uncertain_commit_retains' --tb=short
```

**27 passed, 71 deselected**; `local-related.txt` records the output. These are selected non-DB checks, including the complete routing module. Ruff check/format and `git diff --check` passed on changed files.

`local-db-blocker.txt` records the required-DB attempt (`TC_REQUIRE_DB=1 ... test_public_intake_retry_is_one_persisted_request`): localhost5432 refused connections, so no PostgreSQL tests ran locally. CI uses Python3.11 and the repository's pinned pgvector16 disposable database. No required DB test is silently skipped or claimed as a local pass.

## Regression and review evidence

- `schema-red.txt`:5 original validation failures. `unstorable-red.txt`:3 NUL/Unicode boundary failures; UTF-8 surrogate rejection is also covered.
- Root review's write-then-timeout failure uses a caller-owned storage key so cleanup is possible even when upload never returns. API/storage/fresh-session/retry regressions passed atbcbb40f.
- Migration roundtrips preserve non-default provenance; changed body, parent request, workspace, recipient, subject or note type cannot restore obsolete approval. The expanded PostgreSQL cases passed atbcbb40f. Known send outcomes remain recordable after concurrent request archival.
- `cleanup-abort-red.txt` / `cleanup-abort-green.txt`:2 failures then2 passes. DB abort failure cannot bypass blob compensation; failed deletion logs only a generated opaque key. Positive assignment/unassignment fresh-session persistence is included in the same follow-up.
- `commit-uncertain-red.txt` / `commit-uncertain-green.txt`:2 failures then2 passes. Once COMMIT begins, missing acknowledgement cannot prove rollback. The route retains the attachment and retry record, returns a safe uncertain502 and logs an opaque key/request id. A real PostgreSQL commit-then-raise test verifies persisted row, retained blob and one-upload same-key replay; this newest case passed in the final exact-head CI above.

Synthetic fixture rows are fully removed, including notes, audit events, idempotency records, API keys, users and memberships. Touched legacy tests clean login sessions and all created rows. Counts/identities are asserted after cleanup; no trigger/FK bypass is used. Provider responses are synthetic; no live account/provider delivery is qualified.

Independent root review accepted the cleanup/idempotency flow at `b57cb9b` with no blocking finding and independently reran the four cleanup/uncertainty checks: **4 passed**. A subsequent evidence-only commit does not alter tested product or test code. SMTP integration and migration re-parenting will require new exact-head verification.

## Dependencies

Schema/model scope is approved by #85 comment6503678126. Migration `tc18001_reviewed_replies` currently follows `tc10001_job_leases`; its final parent is subject to Coordinator's slot after the preceding backend/auth migrations. Master updates use pure merge commits, never rebase.

Ruling6504557554 assigns safe sensitive SMTP work exclusively to #86. #88 consumes it only after #86 merges; no duplicate shared transport change is included. Shared auth, FileService, main.py and UI are not edited by this ticket. Frontend reviewed-reply consumer qualification remains open. Only TC Coordinator merges.
