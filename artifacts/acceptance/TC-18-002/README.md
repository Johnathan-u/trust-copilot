# TC-18-002 acceptance evidence

Draft implementation; no completion claim.

- Production baseline: 5b97a33. First RED commit 717b6968c17749f33717ab69a1a58925bce3c92f: CI run 40919867412/build 123609857229, 5 expected failures, 3183 passed,1 external blindpack skip. Precommit/lint/migrations and web e2e passed.
- Extended RED commit 6ffbc91e81a346042e334def38620c520078184b: CI run 40923565341/build 123622965016, 35 failed, 3228 passed,1 external skip. Missing lifecycle/current membership contract dominated; cleanup used a deleted ORM instance ID and one existing empty-email assertion expected 400. Both incidental issues are fixed in implementation. Precommit/lint/migrations and web e2e passed.
- Local isolated schema and unauthenticated-route checks: 16 passed. Raw output in lifecycle-local-green.txt. Initial route registration RED (4 failures) is routes-red.txt; malformed-recipient 4 RED/4 GREEN and reviewer boundary 5 RED evidence is retained. A token-control-character regression failed before its pattern fix; lone-surrogate regressions already pass through Pydantic.
- Python 3.12 runtime uses repository requirements-dev.lock. Local PostgreSQL is unavailable; local-db-attempt.txt records the connection failure, not a behavior RED. GitHub CI uses pinned PostgreSQL 16/pgvector and Python 3.11.

Pending: full DB GREEN at the implementation SHA, independent review, Coordinator migration landing slot and sensitive SMTP failure logging ruling. No live provider/account calls or frontend qualification were performed. Tests include scoped cleanup/count checks, current membership on every private mutation, equal 404 boundaries, hash-only persistence, final-submit replay, durable pre-send intent/post-send commit failure, lost idempotency owner rollback and nondefault downgrade/upgrade with downtime-edit guard.
