# TC-06-003a approval authorization evidence

Claim: [#85/6515545874](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515545874).
Base: `8f0cc07872057007d635e7bee17687f5fadc696b`.

This child scopes golden-answer approval parent lookups, event-history reads,
assignment targets and bulk preflight. It preserves existing permissions and
authorized workflow behavior. Full principal/expanded-domain parents remain
open; golden-library routes and source eligibility are outside this claim.

Actual local regressions use SQLite with FK enforcement and stored user,
membership and session records. The unchanged source fails 40 of 106 cases;
the repair passes all 106. Collection lists 212 new cases plus all 15 existing
approval cases. The 29 collection-safety checks pass.

Required PostgreSQL execution exits 3 before any tests because localhost:5432
refuses connections. This is a concrete qualification gate, not a passing or
skipped integration result. No provider calls or substitute database mocks were
used. See `verification.json` for final code identities, commands and deliberate
negative controls. Publication and merge remain coordinator-owned.
