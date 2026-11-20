# TC-04-007a evidence

Local PostgreSQL runs of the forgot-password enumeration regression. The unfixed handler is `failing-before.txt`. The fixed handler is `passing-after.txt`. The auth files that ran after the fix are `auth-suite.txt`. The interpreter, database, and commands are in `environment.txt`.

Unfixed code (`failing-before.txt`):

- `tests/release/test_forgot_password_enumeration.py`: 1 failed. Request 11 for a known address was 429. The same request for an unknown address was 200. The first ten bodies matched.

Fixed code (`passing-after.txt`):

- The same test: 1 passed. Both addresses returned ten 200 responses with the generic reset message, then one 429 with `Too many requests. Try again later.`

Auth files on the fixed handler (`auth-suite.txt`): 179 passed. No skips.

The in-memory limiter is per process. Sharing it, `Retry-After`, and invite creation limits stay on TC-04-007b. This folder does not accept TC-04-007 or TC-04-007a.
