# TC-06-003g local acceptance evidence

Base `d4f8f38e482532e14d08c28ba0baf6ccc0002a06`; claim #85/6516966183.
The only runtime change is the evidence workspace predicate in
`control_timeline_service.get_control_timeline`.

| Verification                                     | Observed result                                                                   |
| ------------------------------------------------ | --------------------------------------------------------------------------------- |
| Before predicate: actual stored-auth SQLite HTTP | 4 failed, 21 passed                                                               |
| After predicate: same SQLite matrix              | 25 passed                                                                         |
| All database variants collected                  | 50 cases                                                                          |
| Related citation/principal/session controls      | 78 passed                                                                         |
| Safe collection                                  | 29 passed                                                                         |
| Strict PostgreSQL attempt                        | Exit 3 at setup; localhost port 5432 refused                                      |
| Remove evidence workspace predicate in memory    | Expected failure: foreign event displaces own event at limit 1 and inflates total |
| Remove parent workspace predicate in memory      | Expected failure: foreign control returns 200 instead of neutral 404              |

The initial failures cover mixed links at limits 1 and 50, a foreign-only link,
and evidence moved to another workspace. Queries and projections now omit those
events before counting, sorting or limiting. Exact own state/evidence/review/
verification projections preserve the existing API, including its existing
snapshot limit behavior.

The test app changes only the database connection to an owned fixture. Current
membership, explicit-expiry stored sessions, routers and services remain real.
Complete row hashes cover 13 tables, all reads permit SELECT statements only,
and denials assert no child-object lookup. Cleanup uses exact fixture IDs and
checks the full baseline. No schema/FK/trigger bypass, provider or storage mock is
used. Test timestamps are fixed synthetic data; response timestamp instants are
compared across PostgreSQL's aware and SQLite's naive representations.

Unsafe cross-links/moves are attempted inside a SAVEPOINT. If PostgreSQL rejects
one with SQLSTATE 23503 or 23514, the complete state must remain unchanged and the
owned HTTP result must still be correct. The test records a `database_scope_guard`
property and emits a diagnostic warning with the operation, SQLSTATE and
constraint name so CI logs distinguish database protection from service filtering.
Other errors fail. Local SQLite accepted the fixtures, exercising the actual
projection failures; PostgreSQL rejection branches are not locally qualified.

Independent review, exact-head CI and actual PostgreSQL execution remain required.
No full TC-06-003, TC-22-003, provider or owner/viewer completion is claimed.
