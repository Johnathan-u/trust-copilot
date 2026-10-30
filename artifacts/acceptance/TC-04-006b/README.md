# TC-04-006b API acceptance evidence

Base: `0317a1846deb7f66b7a4f33ccd0f21877fec0b0d`.
Branch: `codex/TC-04-006b-logout-all`.
Scope: one new route in `auth.py`, `test_logout_all.py`, child ticket and evidence.
This describes the accompanying local commit, not a completed release or CI run.

## Real-auth controls

The fixture uses real password hashing/login, stored users and memberships,
independent HTTP clients/SIDs, production signing/verification and actual API
routes. One user's second client switches to another workspace. A different
user stays authenticated. Two clients have session-only cookies and one has a
remembered cookie; no authentication dependency or session store is mocked.

- Both same-user clients lose `/auth/me` access after success, including the
  caller, while the foreign user retains all stored sessions and access.
- Supplying a foreign user/SID in an unconsumed JSON body cannot redirect the
  operation. The affected user comes exclusively from current authenticated
  authority. All non-session/non-audit tables remain unchanged.
- Success creates one scoped audit with the actual deleted count and no raw
  token or SID in its details. A revoked client's replay fails without writes.
- Anonymous, bad-signature, expired, revoked, foreign-SID, missing-SID,
  missing/boolean-user, removed/suspended membership, pending onboarding,
  restricted MFA enrollment and API-key contexts are denied. An API key does not
  acquire human authority even alongside a valid cookie. Denials preserve full
  rows and cookie state; the foreign user's access remains valid.
- Delete, audit insert and precommit failure injection affect actual SQLAlchemy
  operations. Each produces safe 503, unchanged full rows and no Set-Cookie;
  all clients remain usable and a fault-free retry succeeds.
- Cookie deletion has empty value, Max-Age zero, Expires, path `/`, HttpOnly,
  SameSite lax and the correct Secure flag. Only the cookie environment predicate
  is controlled for production/development attribute variants; real auth stays
  active. These are response-header controls, not production browser trials.
- Existing logout-current and revoke-others retain their distinct behavior.
  The fixture owns and cleans exact users/workspaces/rows and asserts final
  counts plus unchanged external rows using the existing reviewed authority
  fixture. No trigger/FK or session-replication bypass is used.

## Failure-first and mutation evidence

Before implementation the route returned 404: 21 intended contract cases failed
and both existing-action controls passed. Four additional production-cookie
variants bring the final matrix to 27 cases per database.

After the matrix passed, three temporary mutations each failed one focused
control with exit 1: replacing the user predicate with an unscoped deletion;
excluding the current SID; and committing deletion before the audit helper.
The first two were caught by the incorrect revocation count, and the third by
the full-row rollback invariant. The original source was restored byte-for-byte
before final verification. No mutation code or diagnostic helper is committed.

## Qualification boundary

`verification.txt` records actual commands and results: 201 related local cases,
714 unit passes/11 existing skips, 54 new cases collected, lint/format/diff pass.
Required PostgreSQL execution exits 3 because localhost:5432 refuses connections.
All 27 new PostgreSQL cases still require CI. The new route has no UI consumer
in this increment. Independent review, dependency integration, all four
exact-head jobs and later real multi-browser UI acceptance remain outstanding.

No schema migration or rollback migration is needed. Reverting the route does
not recreate sessions already revoked; those users must authenticate again.
No idle duration, activity definition, warning lead time or retention policy is
chosen here. Parent TC-04-006 remains open.
