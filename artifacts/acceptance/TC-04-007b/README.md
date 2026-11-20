# TC-04-007b evidence

Local PostgreSQL runs of the shared auth limiter. The unfixed handler is `failing-before.txt`. The fixed handler is `passing-after.txt`. The auth files that ran after the fix are `auth-suite.txt`. The interpreter, database, and commands are in `environment.txt`.

Unfixed code (`failing-before.txt`):

- `tests/release/test_auth_rate_limits.py`: 7 failed.
- A second process recorded 10 attempts. This process did not see them. The backend was `_InMemoryBackend`.
- Login, forgot-password, reset-password, resend-verification, and invite verification reached 429 and sent no `Retry-After`.
- The eleventh invite create returned 200 and inserted the row.

Fixed code (`passing-after.txt`):

- The same file: 8 passed. The seven behaviour tests pass. The eighth downgrades `tc04007b_rate_buckets` and upgrades it again.
- The other process's counter is visible. Each 429 above sends `Retry-After`. The eleventh invite is 429 `Too many invites. Try again later.` and inserts no row.

Auth files on the fixed handler (`auth-suite.txt`): 217 passed. No skips. That run includes the forgot-password enumeration file, so the known and unknown 200 bodies and the `reset:ip` order are still covered.

`python -m pytest tests/release -q --tb=line -rs` on the first full pass: 5399 passed, 13 failed, 19 skipped, exit 1, 551.71s. One failure was `test_answer_revision_migration_is_the_only_head`, which still required `tc12004a_answer_revisions` to be the only Alembic head. That pin now walks the single head chain. Re-ran as `test_answer_revision_migration_stays_on_the_single_head`: passed. The other 12 failures are Node 22.23.4 where the tests require Node 24, and a missing `apps/web/node_modules` (typescript, Next, Playwright). They do not import the limiter. A second pass on the same database also reported duplicate primary keys left by the first pass. Those are not in the 5399/13 count.

This folder does not accept TC-04-007 or TC-04-007b.
