# TC-06-002e local acceptance evidence

The frozen basis is TC-06-002 AC1/AC2 and `PRODUCT_SPEC.md`'s requirement to check
indirect object IDs on detail/download/job paths. This increment protects only
export-job artifact metadata. It does not qualify downloaded bytes or close the
parent ticket.

The new suite has 146 collected cases: 73 SQLite and 73 migrated-PostgreSQL cases.
It uses actual jobs routes, signed expiring cookies, stored users, sessions,
memberships and custom-role resolution. Only the database dependency points at
fixture-owned storage. There are no auth, artifact-lookup, storage or provider
overrides. One failure test injects a database read exception to prove that an
error cannot cause a fallback to the untrusted stored result.

Each HTTP read compares full-row hashes of all 13 relevant tables and records
executed statements, requiring SELECT-only access. Cleanup removes only rows in
the newly created workspaces and users, then compares every table to its original
full-row snapshot. SQLite foreign keys stay enabled. The test network guard stays
installed and its blocked-attempt log must not change.

The initial implementation-free run reproduced 58 failures with 15 passing
controls. After the fix, all 73 SQLite cases pass. Three separate negative controls
remove the questionnaire workspace predicate, remove the record workspace
predicate, or copy the stored key; each makes its focused real-HTTP assertion fail.
The actual implementation was restored byte for byte afterward.

PostgreSQL has stronger write guards than the disposable SQLite schema. Two
PostgreSQL branches explicitly require the existing trigger rejection and unchanged
rows; only then do they detach their own nullable reference and perform the
allowed move. SQLite proves the response guard against the inconsistent state
directly. Do not equate those two forms of evidence or claim that the impossible
PostgreSQL state was seeded. Strict PostgreSQL execution remains required in CI.

All existing functions except the result-selection branch in `_public_job` retain
their original AST. The lifecycle return dictionary is identical. Existing job
history unit cases and current-principal/session controls also pass. The shared
result renderer covers cancellation/retry responses without changing action
authorization or mutation logic; the new suite exercises an already-cancelled
response with the same no-write invariant.

See `verification.txt` for commands and actual outcomes. Independent review and
both push/PR build and web-release-e2e checks on the exact final head are pending.
No publication, external storage, provider calls, or account actions were performed.

The first actual build (`41010994109` / `123916590609`) exposed a fixture selector
error in both PostgreSQL move cases: SQLAlchemy names the dialect `postgresql`,
while `move_owned_parent` checked `postgres`. It therefore skipped the expected
trigger-rejection assertion and the committed detach. The later move failed at
the caller's commit with the original `23514`/`23503` protection intact. Correcting
that single literal selects the intended branch; all 31 assertion ASTs and all
runtime bytes are unchanged. The configured-engine condition was independently
evaluated before and after without opening a database connection. Actual repaired
PostgreSQL acceptance remains pending; no constraint or assertion was bypassed.
