# TC-05-003b reconstructed implementation evidence

Branch: `codex/TC-05-003b-grants-recovery`.
Base: published #130 `01914a0e67e0d3c9eba5c19c6960e22f1713d529`.
Scope: [#85 / 6515017225](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515017225).
The earlier local object was lost. This is newly reconstructed source; only the
fresh commands in [verification.txt](verification.txt) support its test claims.
The coordinator handoff records the resulting commit/tree.

## Runtime change

The `members.py` diff adds 25 lines and removes one import line to check permissions before
member reassignment, invitation creation or API-key issuance. A small adapter
computes new permissions and calls the parent's existing current-actor ceiling.
All enabled invite/key flags are new grants; reassignment considers only flags
absent from the target's previous role. Validation, missing-member 404 and the
last-admin guard remain unchanged. No authentication-module, schema, dependency, frontend,
shared test helper or CI file changes are included.

The target custom-role definition is read directly once; builtin grants come from
the existing constant. The boolean resolver catches lookup errors as false, which
would incorrectly imply no requested grants. Direct lookup lets that error fail
before mutation, while the actor-ceiling helper and previous-role checks retain
their existing permission semantics.

## Fresh regression proof

The reconstructed 59-case SQLite matrix on unchanged parent runtime produced
24 failures and 35 passing controls. Failures cover six isolated custom-role
grants, nine builtin grants, two self-assignments, the default editor key, three
isolated missing key permissions and three grants after current-role revocation.
The same test matrix, parent tests and related session checks run after repair;
their actual totals and remaining environment limits are in verification.txt.

A further real stored-auth fault probe on the initial adapter injected a database
read error only after requested-role validation. It reproduced a 200 member change
granting edit to another member despite the actor lacking edit. Two focused
member/invite controls then reproduced the same unauthorized 200 outcome. The
final suite includes both (61 per database); target lookup failures return the
ordinary server error before any row or notification changes. The fault injection
substitutes only a database execution error, never an authorization decision.

The tests mount real auth, members and documents routers. Signed human cookies
have future expiry and stored SID/user/membership rows, with a deliberately stale
admin claim. Expected permission vectors are independently declared in the test.
Only `get_db` and the invitation background task's `SessionLocal` select the owned
database. No authorization, invite, role, notification or provider implementation
is replaced. The fixture clears/restores the provider-selection cache and requires
the real console provider, preventing leaked mocks from other email tests from
satisfying acceptance. Outbound attempts must remain unchanged.

Allowed invitations run the actual console sender, code verification and acceptance
routes, then assert persisted membership and effective permissions. Codes and keys
are consumed in memory and omitted from evidence. Issued keys authenticate genuine
bearer requests to the edit-protected empty documents bulk operation and the
admin-protected members route. The empty operation performs no storage mutation.
Request-created background threads have a bounded join before snapshot/cleanup.

Denials compare every column of every row in 12 tables: users, workspaces,
memberships, sessions, MFA, subscriptions, custom roles, audits, keys, invites,
in-app notifications and notification policies. Cleanup deletes only known new
workspace/user identities, then compares the complete baseline. PostgreSQL uses
existing migrated fixtures without constraint/trigger bypass; SQLite enables FKs.

## Explicit gates

PostgreSQL/full-suite qualification is not inferred from SQLite. Final-head CI,
independent review, actual landed-parent integration and publication capacity are
required. Only the coordinator publishes. Owner/viewer/final-owner semantics,
later issuer revocation at invite acceptance, API-key expiry/attribution/lifecycle,
real provider delivery and full role/principal parents remain open.
