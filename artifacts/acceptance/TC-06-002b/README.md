# TC-06-002b evidence

Source base: `5928f061e2967e9ca717879b0517a66f22f4d6c2`.
Branch: `codex/TC-06-002b-citation-authorization`.
Claim: [#85 comment 6514431612](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514431612).
Scope: one workspace predicate in the existing linked-evidence lookup, one new
HTTP/database regression file, child ticket and this evidence directory.

The root cause was traced from both citation HTTP routes to `compose_citations`:
the control lookup included workspace ownership, while the `EvidenceItem` lookup
used only its ID. The fix adds the authorized workspace to that existing query,
before serialization or counts/strength computation.

The regression used actual SQLite rows with foreign keys enabled, real stored
human/session/membership records, real cookie verification and authorization, and
the actual router/service. It did not mock citation responses, authentication or
query results. Before the fix, three cases failed and five passed:

- Mixed links exposed foreign approved and pending evidence, reporting four
  evidence items where only two belonged to the workspace.
- Foreign-only links exposed two foreign rows and reported `strong` strength
  where the authorized evidence count was zero and strength should be `none`.
- A mixed answer included four approved citations where only two were authorized.

After the lookup repair, all eight local cases passed. Exact response comparisons
also preserve local pending/approved projections, confidence and verification
fields, and the existing distinction between GET 404 and POST omission for
foreign/missing controls. Anonymous/suspended/removed-member requests are denied
by the unchanged real dependencies. Full-row hashes before/after every HTTP read
and after owned fixture cleanup match.

The identical eight PostgreSQL cases are collected but **not locally qualified**.
The strict full backend-suite command exits 3 during database setup because
localhost:5432 refuses connections. No PostgreSQL trigger behavior is inferred
from SQLite. No FK or trigger is disabled; an unexpected PostgreSQL rejection of
the synthetic cross-link will fail setup and must be reported as database
protection separately from the service controls.

See [verification.txt](verification.txt). Independent review and exact-final-head
CI with all sixteen new cases and repository-wide gates remain required. No CI,
runtime auth route, schema, dependency or framework catalog changed. Parent
TC-06-002 and the broader principal/core-workflow matrix remain open.
