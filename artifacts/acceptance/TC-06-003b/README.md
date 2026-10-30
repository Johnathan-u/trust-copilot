# TC-06-003b golden-library authorization evidence

Claim: [#85/6515743132](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515743132).
Base: `24b348dc5908aba6e40169a67ea8dafb88255731` (approved TC-06-003a).

Five ID lookups now bind to the authenticated workspace before projection or
mutation. Existing permissions, per-route missing responses, update/null/status
semantics, review expiry and reuse behavior are preserved. Approval production
code and source/reference eligibility remain outside this change.

The stored-auth SQLite suite reproduces 11 failures on the unchanged parent and
passes all 87 cases with the repair. Collection lists 174 new cases plus 30
existing golden-library/approval cases. Collection safety passes all 29 checks.
Required PostgreSQL mode exits 3 before testing because localhost:5432 refuses
connections. SQLite results do not qualify PostgreSQL.

The fixture observes full rows across ten tables, rejects SQL writes on denied
requests, cleans only exact owned IDs and verifies the original snapshot.
`verification.json` records final source identities, commands, negative controls
and remaining gates. The worker has not published or merged this work. Full
parent tickets remain open.
