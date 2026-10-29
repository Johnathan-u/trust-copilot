# TC-18-001 evidence

Backend implementation is under review. No completion or PostgreSQL GREEN claim is made yet.

- RED branch SHA: `093d60612ae8f330a898cbecc816b05e141ea6c0`.
- RED CI: https://github.com/Johnathan-u/trust-copilot/actions/runs/40922233567 ; build job `123618258154`, tested merge `a426963` (093d606 merged with base76ae791). Result: **21 failed, 3198 passed, 1 skipped** (external blind pack). Failures cover the specified tenant/GET/intake/review/retry regressions; no test setup errors. Web release E2E passed. Companion push run40922225333 failed while starting isolated Postgres and is not a functional result.
- `schema-red.txt`: original five schema failures. `unstorable-red.txt`: NUL and Unicode-normalization boundary failures before fixes.
- Latest local locked Python3.12 command: `PYTHONPATH=. python -m pytest tests/test_trust_request_routing.py tests/release/test_domain_trust_requests.py -q -k 'schema or revision_reaches or TestResolveWorkspace or TestAttachmentValidation' --tb=short` from apps/api. **19 passed, 67 deselected**, one Alembic configuration warning; see `local-related.txt`. This validates only the selected non-DB checks.
- Ruff check and format passed on all changed Python files; `git diff --check` passed.
- `local-db-blocker.txt`: `TC_REQUIRE_DB=1 PYTHONPATH=. python -m pytest tests/release/test_domain_trust_requests.py::test_public_intake_retry_is_one_persisted_request -q --tb=short` exits because localhost5432 refuses connections. No PostgreSQL tests ran locally. CI provides the pinned pgvector16 test service.

Schema/model scope is approved by #85 comment6503678126. This ticket's landing slot follows TC-07-002 and precedes TC-17-004. The migration is aligned to current master head `tc10001_job_leases` at publication; a later Coordinator slot ruling may require a separate parent-only commit. Master updates use merge commits; no rebase. Full CI GREEN, independent review, migration landing-slot confirmation and frontend consumer qualification remain pending. No live provider delivery qualification is claimed.
