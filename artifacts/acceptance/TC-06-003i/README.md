# TC-06-003i acceptance evidence

The four runtime substitutions bind article creation to its already-authorized
effective workspace and remove the null-owner exemption from PATCH and DELETE.
Everything outside those three handlers retains its original AST, including public
reads, policy acknowledgment, request schemas and response rendering.

Fresh tests use real routes, signed expiring cookies, stored users/sessions,
current memberships and custom permissions. Only the database dependency points
to fixture-owned storage. The SQLite schema uses actual models with foreign keys
enabled; the PostgreSQL variant uses the repository's migrated database fixture.
No auth, audit, article-lookup or storage mocks are added.

| Check | Observed local result |
| --- | --- |
| New SQLite tests before implementation | 13 failed, 51 passed |
| Same SQLite tests after four substitutions | 64 passed |
| New tests plus existing article API collection | 139 collected (128 new, 11 existing) |
| Safe collection/network controls | 29 passed |
| Strict full API suite | Exit 3 before tests: PostgreSQL unavailable |
| Revert duplicate workspace only, in memory | Expected focused failure |
| Revert persistence workspace only, in memory | Expected focused failure |
| Restore null-owner PATCH exemption only, in memory | Expected focused failure |
| Restore null-owner DELETE exemption only, in memory | Expected focused failure |

Each response is checked against full-row hashes for ten tables. Denials and reads
must execute SELECTs only and emit no audit mutation event. Successful operations
must change exactly the intended row IDs, including a real acknowledgment cascade
on deletion. Cleanup deletes exact owned IDs, restores the original complete-row
snapshot, and requires the network guard's blocked-attempt log to remain unchanged.

The red run demonstrates the actual null-owner and duplicate defects, the existing
zero foreign-key failure, and the null-owner write bypass. Each independent negative
control catches one production substitution being reverted. Controls execute only in
separate Python processes and never edit the production source on disk.

Raw outputs are under `commands/`; command details and source hashes are in
`verification.txt`. PostgreSQL cases are authored and collected, not locally
qualified. The strict complete-suite attempt cannot connect to localhost port 5432.
Independent review, real PostgreSQL execution and exact-head CI remain required.
No provider/model calls, storage requests, schema changes or constraint bypasses occurred.
